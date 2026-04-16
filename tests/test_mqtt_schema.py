"""
Tests for MQTT message schema validation.
Validates telemetry, state-change, and alert payloads against spec.
"""
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEVICE_ID_PATTERN = re.compile(r"^core2-[a-z0-9]{4}$")
VALID_STATES = {"suitable", "not_suitable", "transitioning"}
ISO8601_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def validate_telemetry(payload: dict) -> list[str]:
    """Validate a telemetry payload. Returns list of errors."""
    errors = []
    required = ["device_id", "location_id", "ts_utc", "accel_rms", "spl_db", "seq"]

    for field in required:
        if field not in payload:
            errors.append(f"missing field '{field}'")

    if "device_id" in payload and not DEVICE_ID_PATTERN.match(payload["device_id"]):
        errors.append(f"device_id format invalid: {payload['device_id']}")

    if "ts_utc" in payload and not ISO8601_PATTERN.match(payload["ts_utc"]):
        errors.append(f"ts_utc not ISO 8601 UTC: {payload['ts_utc']}")

    for field in ["accel_rms", "spl_db"]:
        if field in payload and payload[field] is None:
            errors.append(f"{field} must not be null")
        if field in payload and not isinstance(payload[field], (int, float)):
            errors.append(f"{field} must be numeric")

    if "seq" in payload and not isinstance(payload["seq"], int):
        errors.append("seq must be integer")

    return errors


def validate_state(payload: dict) -> list[str]:
    """Validate a state-change payload."""
    errors = []

    if "state" in payload and payload["state"] not in VALID_STATES:
        errors.append(f"invalid state: {payload['state']}")

    if "prev_state" in payload and payload["prev_state"] not in VALID_STATES:
        errors.append(f"invalid prev_state: {payload['prev_state']}")

    if "score" in payload:
        if not isinstance(payload["score"], (int, float)):
            errors.append("score must be numeric")
        elif not (0 <= payload["score"] <= 100):
            errors.append(f"score out of range: {payload['score']}")

    return errors


# --- Telemetry tests ---

def test_valid_telemetry():
    payload = {
        "device_id": "core2-a1b2",
        "location_id": "library-1f",
        "ts_utc": "2026-04-17T14:23:01.000Z",
        "accel_rms": 0.32,
        "spl_db": 61.4,
        "seq": 4201,
    }
    errors = validate_telemetry(payload)
    assert errors == [], f"Unexpected errors: {errors}"


def test_telemetry_missing_field():
    payload = {
        "device_id": "core2-a1b2",
        "location_id": "library-1f",
        "ts_utc": "2026-04-17T14:23:01.000Z",
        "accel_rms": 0.32,
        # missing spl_db
        "seq": 4201,
    }
    errors = validate_telemetry(payload)
    assert any("spl_db" in e for e in errors)


def test_telemetry_bad_device_id():
    payload = {
        "device_id": "device-123",
        "location_id": "library-1f",
        "ts_utc": "2026-04-17T14:23:01.000Z",
        "accel_rms": 0.32,
        "spl_db": 61.4,
        "seq": 4201,
    }
    errors = validate_telemetry(payload)
    assert any("device_id" in e for e in errors)


def test_telemetry_null_numeric():
    payload = {
        "device_id": "core2-a1b2",
        "location_id": "library-1f",
        "ts_utc": "2026-04-17T14:23:01.000Z",
        "accel_rms": None,
        "spl_db": 61.4,
        "seq": 4201,
    }
    errors = validate_telemetry(payload)
    assert any("accel_rms" in e for e in errors)


def test_telemetry_bad_timestamp():
    payload = {
        "device_id": "core2-a1b2",
        "location_id": "library-1f",
        "ts_utc": "2026-04-17T14:23:01+05:00",
        "accel_rms": 0.32,
        "spl_db": 61.4,
        "seq": 4201,
    }
    errors = validate_telemetry(payload)
    assert any("ts_utc" in e for e in errors)


# --- State-change tests ---

def test_valid_state_change():
    payload = {
        "device_id": "core2-a1b2",
        "location_id": "library-1f",
        "ts_utc": "2026-04-17T14:23:30.000Z",
        "score": 67,
        "state": "suitable",
        "prev_state": "not_suitable",
        "window_sec": 30,
    }
    errors = validate_state(payload)
    assert errors == [], f"Unexpected errors: {errors}"


def test_invalid_state_value():
    payload = {
        "state": "occupied",
        "prev_state": "suitable",
        "score": 50,
    }
    errors = validate_state(payload)
    assert any("state" in e for e in errors)


def test_score_out_of_range():
    payload = {
        "state": "suitable",
        "prev_state": "not_suitable",
        "score": 150,
    }
    errors = validate_state(payload)
    assert any("score" in e for e in errors)
