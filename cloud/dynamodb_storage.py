"""
Smart Space Pulse — DynamoDB Storage Backend

Replaces the SQLite storage layer with two DynamoDB tables:

  ssp-telemetry  PK=location_id (S), SK=ts_utc (S)   — append-only readings
  ssp-state      PK=location_id (S)                  — current state per location

Telemetry items carry an `expire_at` epoch attribute consumed by DynamoDB TTL,
so raw readings auto-purge after ~7 days without explicit deletes.
"""
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3

logger = logging.getLogger("dynamodb_storage")

DEFAULT_REGION          = "us-east-1"
DEFAULT_TELEMETRY_TABLE = "ssp-telemetry"
DEFAULT_STATE_TABLE     = "ssp-state"
DEFAULT_TTL_DAYS        = 7


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class DynamoDBStorage:
    """boto3-backed storage interface for telemetry and per-location state."""

    def __init__(self,
                 region: str | None = None,
                 telemetry_table: str | None = None,
                 state_table: str | None = None,
                 ttl_days: int = DEFAULT_TTL_DAYS):
        region = region or os.getenv("AWS_REGION", DEFAULT_REGION)
        self.telemetry_table_name = telemetry_table or os.getenv(
            "DYNAMO_TELEMETRY_TABLE", DEFAULT_TELEMETRY_TABLE)
        self.state_table_name = state_table or os.getenv(
            "DYNAMO_STATE_TABLE", DEFAULT_STATE_TABLE)
        self.ttl_seconds = ttl_days * 86400

        self._dynamodb = boto3.resource("dynamodb", region_name=region)
        self.telemetry = self._dynamodb.Table(self.telemetry_table_name)
        self.state     = self._dynamodb.Table(self.state_table_name)
        logger.info("DynamoDB storage ready (region=%s telemetry=%s state=%s)",
                    region, self.telemetry_table_name, self.state_table_name)

    # ---- writes -----------------------------------------------------------

    def write_telemetry(self, payload: dict) -> None:
        """Append a single telemetry reading."""
        expire_at = int(datetime.now(timezone.utc).timestamp()) + self.ttl_seconds
        self.telemetry.put_item(Item={
            "location_id": payload["location_id"],
            "ts_utc":      payload["ts_utc"],
            "device_id":   payload["device_id"],
            "spl_db":      Decimal(str(payload["spl_db"])),
            "seq":         int(payload["seq"]),
            "expire_at":   expire_at,
        })

    def update_state(self, location_id: str, state: str, score: float) -> None:
        """Upsert the current state for one location."""
        self.state.put_item(Item={
            "location_id": location_id,
            "state":       state,
            "score":       Decimal(str(round(score, 2))),
            "updated_at":  _now_iso(),
        })

    # ---- reads ------------------------------------------------------------

    def query_recent_spl(self, location_id: str, n: int = 30) -> list[float]:
        """Return the n most recent spl_db readings (oldest first)."""
        return [it["spl_db"] for it in self.query_recent(location_id, n)]

    def query_recent(self, location_id: str, n: int = 30) -> list[dict]:
        """Return the n most recent telemetry items (oldest first), each
        as {"ts_utc": str, "spl_db": float}.
        """
        resp = self.telemetry.query(
            KeyConditionExpression="location_id = :loc",
            ExpressionAttributeValues={":loc": location_id},
            ScanIndexForward=False,
            Limit=n,
            ProjectionExpression="ts_utc, spl_db",
        )
        items = list(reversed(resp.get("Items", [])))
        return [{"ts_utc": it["ts_utc"], "spl_db": float(it["spl_db"])} for it in items]

    def get_state(self, location_id: str) -> dict | None:
        resp = self.state.get_item(Key={"location_id": location_id})
        return resp.get("Item")

    def list_states(self) -> list[dict]:
        items, last_key = [], None
        while True:
            kwargs = {}
            if last_key:
                kwargs["ExclusiveStartKey"] = last_key
            resp = self.state.scan(**kwargs)
            items.extend(resp.get("Items", []))
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                break
        return items
