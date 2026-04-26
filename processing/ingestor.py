"""
Smart Space Pulse — MQTT Ingestor

Subscribes to ssp/#, validates schema, and writes to storage.
Supports AWS IoT Core (TLS mutual auth) and local broker fallback.
"""
import json
import logging
import os
import re
import ssl
import sys

from dotenv import load_dotenv
load_dotenv()

import paho.mqtt.client as mqtt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from processing.storage import Storage
from processing.windower import Windower

logger = logging.getLogger("ingestor")

DEVICE_ID_PATTERN = re.compile(r"^Core2Kit[a-zA-Z0-9-]*$")
ISO8601_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
VALID_STATES = {"suitable", "not_suitable", "transitioning"}

TELEMETRY_REQUIRED = ["device_id", "location_id", "ts_utc", "spl_db", "seq"]
TELEMETRY_NUMERIC = ["spl_db"]


def validate_telemetry(payload: dict) -> list[str]:
    """Validate a telemetry payload. Returns list of error strings."""
    errors = []
    for field in TELEMETRY_REQUIRED:
        if field not in payload:
            errors.append(f"missing field '{field}'")

    if "device_id" in payload and not DEVICE_ID_PATTERN.match(payload.get("device_id", "")):
        errors.append(f"device_id format invalid: {payload.get('device_id')}")

    if "ts_utc" in payload and not ISO8601_PATTERN.match(payload.get("ts_utc", "")):
        errors.append(f"ts_utc not ISO 8601 UTC: {payload.get('ts_utc')}")

    for field in TELEMETRY_NUMERIC:
        if field in payload and payload[field] is None:
            errors.append(f"{field} must not be null")
        if field in payload and not isinstance(payload[field], (int, float)):
            errors.append(f"{field} must be numeric")

    if "seq" in payload and not isinstance(payload.get("seq"), int):
        errors.append("seq must be integer")

    return errors


def validate_state_change(payload: dict) -> list[str]:
    """Validate a state-change payload. Returns list of error strings."""
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


def _build_tls_context(ca_path: str, cert_path: str, key_path: str) -> ssl.SSLContext:
    """Build an SSL context for AWS IoT Core mutual TLS authentication."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_verify_locations(ca_path)
    ctx.load_cert_chain(cert_path, key_path)
    return ctx


class Ingestor:
    """MQTT subscriber that validates and stores telemetry messages."""

    def __init__(self, host: str = "localhost", port: int = 1883,
                 use_tls: bool = False, ca_path: str = None,
                 cert_path: str = None, key_path: str = None,
                 storage: Storage = None):
        self.host = host
        self.port = port
        self.messages_received_total = 0
        self.schema_validation_errors_total = 0
        self._storage = storage or Storage()
        self._windower = Windower()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                  client_id="Core2Kit-ingestor")

        if use_tls:
            if not ca_path or not cert_path or not key_path:
                raise ValueError("TLS enabled but certificate paths not provided. "
                                 "Set MQTT_CA_CERT, MQTT_CLIENT_CERT, MQTT_CLIENT_KEY in .env")
            ctx = _build_tls_context(ca_path, cert_path, key_path)
            self.client.tls_set_context(ctx)
            self.client.tls_insecure_set(False)
            logger.info("TLS enabled — connecting to %s:%d with client cert", host, port)
        else:
            logger.info("TLS disabled — connecting to %s:%d (plain MQTT)", host, port)

    def on_connect(self, client, userdata, flags, rc, properties=None):
        logger.info("Connected to MQTT broker at %s:%d (rc=%s)", self.host, self.port, rc)
        client.subscribe("ssp/#", qos=1)

    def _route_message(self, topic: str, payload: dict):
        """Route a validated message based on its topic."""
        parts = topic.split("/")
        # Expected: ssp/{location_id}/{type}
        if len(parts) < 3:
            logger.warning("Unexpected topic format: %s", topic)
            return

        msg_type = parts[-1]

        if msg_type == "telemetry":
            errors = validate_telemetry(payload)
            if errors:
                self.schema_validation_errors_total += 1
                device_id = payload.get("device_id", "?")
                logger.error("Schema error on %s: %s", device_id, "; ".join(errors))
                logger.warning("Skipping malformed message on topic %s", topic)
                return
            self._storage.write_telemetry(payload)
            device_id = payload.get("device_id", "?")
            seq = payload.get("seq", "?")
            logger.info("Received telemetry from %s seq=%s", device_id, seq)

            # Feed through windower for scoring; always persist current state to DB
            result = self._windower.ingest(payload)
            if result:
                self._storage.update_state(
                    result["location_id"], result["state"], result["score"]
                )
                if result["changed"]:
                    logger.info("STATE: %s -> %s (score=%.1f)",
                                result["prev_state"], result["state"], result["score"])

        elif msg_type == "state":
            errors = validate_state_change(payload)
            if errors:
                self.schema_validation_errors_total += 1
                logger.error("State schema error: %s", "; ".join(errors))
                return
            self._storage.update_state(
                payload["location_id"], payload["state"], payload["score"]
            )
            logger.info("State update: %s -> %s (score=%.1f)",
                        payload["location_id"], payload["state"], payload["score"])

        elif msg_type == "alert":
            logger.info("Alert from %s: %s spl_db=%.1f",
                        payload.get("device_id", "?"),
                        payload.get("alert_type", "?"),
                        payload.get("spl_db", 0.0))

        elif msg_type == "heartbeat":
            logger.debug("Heartbeat from %s uptime=%s",
                         payload.get("device_id", "?"),
                         payload.get("uptime_sec", "?"))

    def on_message(self, client, userdata, msg):
        self.messages_received_total += 1
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except json.JSONDecodeError:
            self.schema_validation_errors_total += 1
            logger.error("Invalid JSON on topic %s", msg.topic)
            return
        except UnicodeDecodeError:
            self.schema_validation_errors_total += 1
            logger.error("Non-UTF8 payload on topic %s", msg.topic)
            return

        try:
            self._route_message(msg.topic, payload)
        except Exception:
            logger.exception("Unexpected error processing message on %s", msg.topic)

    def start(self):
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect(self.host, self.port, keepalive=60)
        logger.info("Starting ingestor loop...")
        self.client.loop_forever()


if __name__ == "__main__":
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s.000Z [%(levelname)-5s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    use_tls = os.getenv("MQTT_USE_TLS", "false").lower() == "true"
    ingestor = Ingestor(
        host=os.getenv("MQTT_HOST", "localhost"),
        port=int(os.getenv("MQTT_PORT", "8883" if use_tls else "1883")),
        use_tls=use_tls,
        ca_path=os.getenv("MQTT_CA_CERT"),
        cert_path=os.getenv("MQTT_CLIENT_CERT"),
        key_path=os.getenv("MQTT_CLIENT_KEY"),
    )
    ingestor.start()
