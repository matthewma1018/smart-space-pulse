"""
Smart Space Pulse — Serial Logger

Logs every published MQTT message to UART at 115200 baud.
Format: [ISO8601] TOPIC | JSON_PAYLOAD
"""
import json
import sys


def log_message(topic: str, payload: dict) -> None:
    """Log a published message to serial output.

    Args:
        topic: MQTT topic string.
        payload: Message payload as a dict.
    """
    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"
    print(f"[{ts}] {topic} | {json.dumps(payload)}", flush=True)
