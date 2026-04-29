"""
Smart Space Pulse — Storage Backend

Writes telemetry and state data to SQLite.
"""
import logging
import os
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger("storage")


_SCHEMA = """
    CREATE TABLE IF NOT EXISTS raw_telemetry (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id    TEXT    NOT NULL,
        location_id  TEXT    NOT NULL,
        ts_utc       TEXT    NOT NULL,
        spl_db       REAL    NOT NULL,
        seq          INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS location_state (
        location_id  TEXT    PRIMARY KEY,
        state        TEXT    NOT NULL,
        score        REAL    NOT NULL,
        updated_at   TEXT    NOT NULL
    );
"""


class Storage:
    """SQLite storage interface for telemetry data.

    A fresh connection is opened per method call so the dashboard
    (multi-threaded Streamlit reruns) and the ingestor (separate process)
    can both read/write the same db file without sharing connection state.
    """

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = os.getenv("SQLITE_PATH", "data/ssp.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._db_path = db_path
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, timeout=5)

    def write_telemetry(self, payload: dict) -> None:
        """Write a telemetry payload to storage."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO raw_telemetry (device_id, location_id, ts_utc, spl_db, seq) "
                "VALUES (?, ?, ?, ?, ?)",
                (payload["device_id"], payload["location_id"], payload["ts_utc"],
                 payload["spl_db"], payload["seq"]),
            )

    def update_state(self, location_id: str, state: str, score: float) -> None:
        """Update the current state for a location."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO location_state (location_id, state, score, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (location_id, state, score, now),
            )

    # ---- reads (matches the DynamoDBStorage interface so the dashboard
    #            can drop us in as a fallback when AWS is unreachable) -----

    def query_recent(self, location_id: str, n: int = 30) -> list[dict]:
        """Return the n most recent telemetry items, oldest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT ts_utc, spl_db FROM raw_telemetry "
                "WHERE location_id = ? ORDER BY id DESC LIMIT ?",
                (location_id, n),
            ).fetchall()
        return [{"ts_utc": r[0], "spl_db": float(r[1])} for r in reversed(rows)]

    def query_recent_spl(self, location_id: str, n: int = 30) -> list[float]:
        return [it["spl_db"] for it in self.query_recent(location_id, n)]

    def list_states(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT location_id, state, score, updated_at FROM location_state"
            ).fetchall()
        return [
            {"location_id": r[0], "state": r[1], "score": float(r[2]), "updated_at": r[3]}
            for r in rows
        ]

    def close(self):
        """No-op: connections are opened per call."""
        pass
