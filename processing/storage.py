"""
Smart Space Pulse — Storage Backend

Writes telemetry and state data to SQLite (default), InfluxDB, or JSONL files.
"""
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger("storage")


def _init_sqlite(db_path: str):
    """Initialize SQLite tables."""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS raw_telemetry (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id    TEXT    NOT NULL,
            location_id  TEXT    NOT NULL,
            ts_utc       TEXT    NOT NULL,
            accel_rms    REAL    NOT NULL,
            spl_db       REAL    NOT NULL,
            seq          INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS location_state (
            location_id  TEXT    PRIMARY KEY,
            state        TEXT    NOT NULL,
            score        REAL    NOT NULL,
            updated_at   TEXT    NOT NULL
        );
    """)
    conn.commit()
    return conn


class Storage:
    """Unified storage interface for telemetry data."""

    def __init__(self, backend: str = "sqlite", **kwargs):
        self.backend = backend
        if backend == "sqlite":
            db_path = kwargs.get("path", "data/ssp.db")
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            self._conn = _init_sqlite(db_path)
        elif backend == "file":
            self._file_dir = kwargs.get("path", "data/raw")
            os.makedirs(self._file_dir, exist_ok=True)
        else:
            raise ValueError(f"Unknown storage backend: {backend}")

    def write_telemetry(self, payload: dict) -> None:
        """Write a telemetry payload to storage."""
        if self.backend == "sqlite":
            self._conn.execute(
                "INSERT INTO raw_telemetry (device_id, location_id, ts_utc, accel_rms, spl_db, seq) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (payload["device_id"], payload["location_id"], payload["ts_utc"],
                 payload["accel_rms"], payload["spl_db"], payload["seq"]),
            )
            self._conn.commit()
        elif self.backend == "file":
            date_str = payload["ts_utc"][:10]
            filepath = os.path.join(self._file_dir, f"{date_str}.jsonl")
            with open(filepath, "a") as f:
                f.write(json.dumps(payload) + "\n")

    def update_state(self, location_id: str, state: str, score: float) -> None:
        """Update the current state for a location."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"
        if self.backend == "sqlite":
            self._conn.execute(
                "INSERT OR REPLACE INTO location_state (location_id, state, score, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (location_id, state, score, now),
            )
            self._conn.commit()

    def close(self):
        """Close storage connections."""
        if self.backend == "sqlite" and hasattr(self, "_conn"):
            self._conn.close()
