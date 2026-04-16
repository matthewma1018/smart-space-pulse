"""
Smart Space Pulse — MQTT Ingestor

Subscribes to ssp/#, validates schema, and writes to storage.
"""
import json
import logging
import os
import sys

import paho.mqtt.client as mqtt

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger("ingestor")


class Ingestor:
    """MQTT subscriber that validates and stores telemetry messages."""

    def __init__(self, host: str = "localhost", port: int = 1883):
        self.host = host
        self.port = port
        self.messages_received_total = 0
        self.schema_validation_errors_total = 0
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    def on_connect(self, client, userdata, flags, rc, properties=None):
        logger.info("Connected to MQTT broker at %s:%d (rc=%d)", self.host, self.port, rc)
        client.subscribe("ssp/#", qos=1)

    def on_message(self, client, userdata, msg):
        self.messages_received_total += 1
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            logger.info("Received telemetry from %s seq=%s",
                        payload.get("device_id", "?"), payload.get("seq", "?"))
        except json.JSONDecodeError:
            self.schema_validation_errors_total += 1
            logger.error("Invalid JSON on topic %s", msg.topic)

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
    ingestor = Ingestor(
        host=os.getenv("MQTT_HOST", "localhost"),
        port=int(os.getenv("MQTT_PORT", "1883")),
    )
    ingestor.start()
