"""
Smart Space Pulse — Cloud Inference Lambda

Triggered by an AWS IoT Core Rule on `ssp/+/telemetry`. For each incoming
sensor reading it:

  1. Validates the payload.
  2. Appends the reading to the `ssp-telemetry` DynamoDB table.
  3. Queries the most recent 30 readings for that location.
  4. If a full window is available, runs logistic-regression inference
     (rule-based fallback if the model file is missing or fails to load),
     applies hysteresis against the previous persisted state, and writes
     the new state to the `ssp-state` table.

This handler replaces the local `processing.ingestor` + `processing.windower`
+ `processing.model.inference` pipeline. The LSTM scorer is intentionally
omitted — PyTorch exceeds the standard Lambda zip limit; logistic regression
gives near-identical accuracy on this dataset for a fraction of the size.
"""
import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

WINDOW_SIZE          = 30
SCORE_HIGH_THRESHOLD = 65
SCORE_LOW_THRESHOLD  = 55
TTL_DAYS             = 7

REGION          = os.environ.get("AWS_REGION", "us-east-1")
TELEMETRY_TABLE = os.environ.get("DYNAMO_TELEMETRY_TABLE", "ssp-telemetry")
STATE_TABLE     = os.environ.get("DYNAMO_STATE_TABLE", "ssp-state")
MODEL_PATH      = os.environ.get("LOGISTIC_MODEL_PATH", "/var/task/logistic_model.joblib")

_dynamodb  = boto3.resource("dynamodb", region_name=REGION)
_telemetry = _dynamodb.Table(TELEMETRY_TABLE)
_state     = _dynamodb.Table(STATE_TABLE)

_logistic = None
_logistic_loaded = False


def _load_logistic():
    """Lazy-load the logistic model; cache across warm invocations."""
    global _logistic, _logistic_loaded
    if _logistic_loaded:
        return _logistic
    _logistic_loaded = True
    if os.path.exists(MODEL_PATH):
        try:
            import joblib
            _logistic = joblib.load(MODEL_PATH)
            logger.info("Loaded logistic model from %s", MODEL_PATH)
        except Exception:
            logger.exception("Failed to load logistic model")
    else:
        logger.warning("No logistic model at %s — using rule-based scorer", MODEL_PATH)
    return _logistic


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _window_features(spl: list[float]) -> list[float]:
    n = len(spl)
    mean = sum(spl) / n
    std  = (sum((x - mean) ** 2 for x in spl) / n) ** 0.5
    p90  = sorted(spl)[min(int(0.9 * n), n - 1)]
    mx   = max(spl)
    if std < 1e-6:
        spikes = 0
    else:
        thresh = mean + 1.5 * std
        spikes = sum(1 for x in spl if x > thresh)
    return [mean, std, p90, mx, float(spikes)]


def _rule_based_score(features: list[float]) -> float:
    spl_mean, _, spl_p90, _, spikes = features
    if   spl_mean < 55: noise_score = 0
    elif spl_mean < 70: noise_score = (spl_mean - 55) / 15.0 * 50
    else:               noise_score = 50 + (spl_mean - 70) / 30.0 * 30
    spike_score = max(0, (spl_p90 - 75) / 25.0) * 20
    burst_score = min(spikes, 8) / 8.0 * 10
    return max(0.0, min(100.0, 100.0 - noise_score - spike_score - burst_score))


def _score_logistic(spl_samples: list[float]) -> float | None:
    model = _load_logistic()
    if model is None:
        return None
    features = [_window_features(spl_samples)]
    X = model["scaler"].transform(features)
    prob = float(model["model"].predict_proba(X)[0][1])
    return max(0.0, min(100.0, prob * 100.0))


def _validate(payload: dict) -> str | None:
    for f in ("device_id", "location_id", "ts_utc", "spl_db"):
        if f not in payload:
            return f"missing field '{f}'"
    if not isinstance(payload["spl_db"], (int, float)):
        return "spl_db must be numeric"
    return None


def _write_telemetry(payload: dict) -> None:
    expire_at = int(datetime.now(timezone.utc).timestamp()) + TTL_DAYS * 86400
    item = {
        "location_id": payload["location_id"],
        "ts_utc":      payload["ts_utc"],
        "device_id":   payload["device_id"],
        "spl_db":      Decimal(str(payload["spl_db"])),
        "expire_at":   expire_at,
    }
    if "seq" in payload:
        item["seq"] = int(payload["seq"])
    _telemetry.put_item(Item=item)


def _query_recent(location_id: str, n: int = WINDOW_SIZE) -> list[float]:
    resp = _telemetry.query(
        KeyConditionExpression="location_id = :loc",
        ExpressionAttributeValues={":loc": location_id},
        ScanIndexForward=False,
        Limit=n,
        ProjectionExpression="ts_utc, spl_db",
    )
    items = list(reversed(resp.get("Items", [])))
    return [float(it["spl_db"]) for it in items]


def _read_prev_state(location_id: str) -> str | None:
    resp = _state.get_item(Key={"location_id": location_id})
    item = resp.get("Item")
    return item["state"] if item else None


def _apply_hysteresis(score: float, prev_state: str | None) -> str:
    if score >= SCORE_HIGH_THRESHOLD:
        return "suitable"
    if score < SCORE_LOW_THRESHOLD:
        return "not_suitable"
    return prev_state or "not_suitable"


def _write_state(location_id: str, state: str, score: float) -> None:
    _state.put_item(Item={
        "location_id": location_id,
        "state":       state,
        "score":       Decimal(str(round(score, 2))),
        "updated_at":  _now_iso(),
    })


def lambda_handler(event, context):
    logger.info("Event: %s", json.dumps(event, default=str))

    err = _validate(event)
    if err:
        logger.warning("Validation failed: %s", err)
        return {"status": "validation_failed", "error": err}

    _write_telemetry(event)

    location_id = event["location_id"]
    spl_samples = _query_recent(location_id, WINDOW_SIZE)

    if len(spl_samples) < WINDOW_SIZE:
        logger.info("Buffering for %s: %d/%d samples",
                    location_id, len(spl_samples), WINDOW_SIZE)
        return {"status": "buffering", "samples": len(spl_samples)}

    method = "logistic"
    score = _score_logistic(spl_samples)
    if score is None:
        method = "rule_based"
        score = _rule_based_score(_window_features(spl_samples))

    prev_state = _read_prev_state(location_id)
    new_state  = _apply_hysteresis(score, prev_state)
    _write_state(location_id, new_state, score)

    logger.info("location=%s method=%s score=%.1f state=%s (prev=%s)",
                location_id, method, score, new_state, prev_state)

    return {
        "status":      "ok",
        "location_id": location_id,
        "score":       round(score, 2),
        "state":       new_state,
        "prev_state":  prev_state,
        "method":      method,
    }
