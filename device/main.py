"""
Smart Space Pulse — Device Entry Point
M5Stack Core2 / MicroPython

Usage:
    python device/main.py --sim                           # simulate quiet library
    python device/main.py --sim --profile busy            # simulate busy period
    python device/main.py --sim --profile transition      # quiet -> busy -> quiet
    python device/main.py --sim --duration 60             # run for 60 seconds
"""
import argparse
import json
import logging
import os
import random
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from device.feature_extractor import extract_window
from device.serial_logger import log_message
from device.edge_policy import classify

logger = logging.getLogger("device")

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

# Simulation profiles: spl_db range
PROFILES = {
    "quiet": {"spl": (32.0, 45.0)},
    "busy": {"spl": (70.0, 92.0)},
    "transition": None,  # handled separately
}


def generate_sample(profile: str, seq: int, device_id: str, location_id: str,
                     drift: float = 0.0) -> dict:
    """Generate a single simulated telemetry sample.

    Args:
        profile: One of 'quiet', 'busy', 'transition'.
        seq: Sequence number.
        device_id: Device identifier.
        location_id: Location identifier.
        drift: Slow drift factor to add realism (0-1).

    Returns:
        Telemetry payload dict.
    """
    if profile == "transition":
        # Cycle through phases: quiet -> ramp up -> busy -> ramp down -> quiet
        cycle_pos = (seq % 120) / 120.0  # 2-minute cycle
        if cycle_pos < 0.25:
            spl_range = (32.0, 45.0)
        elif cycle_pos < 0.40:
            t = (cycle_pos - 0.25) / 0.15
            spl_range = (32.0 + t * 38.0, 45.0 + t * 35.0)
        elif cycle_pos < 0.65:
            spl_range = (70.0, 92.0)
        elif cycle_pos < 0.80:
            t = (cycle_pos - 0.65) / 0.15
            spl_range = (70.0 - t * 38.0, 92.0 - t * 47.0)
        else:
            spl_range = (32.0, 45.0)
    else:
        p = PROFILES[profile]
        spl_range = p["spl"]

    spl_db = round(random.uniform(*spl_range) + drift * random.gauss(0, 0.5), 1)
    spl_db = max(20.0, spl_db)

    ts_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"
    return {
        "device_id": device_id,
        "location_id": location_id,
        "ts_utc": ts_utc,
        "spl_db": spl_db,
        "seq": seq,
    }


def simulate(args):
    """Run simulation mode: generate and publish telemetry at 1 Hz."""
    import paho.mqtt.client as mqtt

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    def on_connect(c, userdata, flags, rc, properties=None):
        logger.info("Simulator connected to %s:%d (rc=%s)", args.host, args.port, rc)

    def on_disconnect(c, userdata, flags, rc, properties=None):
        logger.warning("Simulator disconnected (rc=%s)", rc)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    try:
        client.connect(args.host, args.port, keepalive=60)
    except ConnectionRefusedError:
        logger.error("Cannot connect to %s:%d — is the broker running?", args.host, args.port)
        logger.info("Falling back to publish-less mode (logging only)")
        client = None

    topic = f"ssp/{args.location}/telemetry"
    seq = args.start_seq
    start = time.time()
    duration = args.duration if args.duration > 0 else float("inf")

    logger.info("Simulating '%s' profile on %s (device=%s, location=%s)",
                args.profile, topic, args.device, args.location)
    logger.info("Duration: %s", f"{args.duration}s" if args.duration > 0 else "until Ctrl-C")

    try:
        while time.time() - start < duration:
            sample = generate_sample(args.profile, seq, args.device, args.location)
            payload_json = json.dumps(sample)

            if client:
                client.loop(0.01)
                result = client.publish(topic, payload_json, qos=1)
                if result.rc != mqtt.MQTT_ERR_SUCCESS:
                    logger.warning("Publish failed (rc=%d)", result.rc)

            log_message(topic, sample)

            # Run edge policy for on-device display feedback
            edge_state = classify(sample["spl_db"])
            logger.debug("Edge policy: %s (spl=%.1f)",
                         edge_state, sample["spl_db"])

            seq += 1
            time.sleep(1.0)

    except KeyboardInterrupt:
        logger.info("Stopped after %d samples (seq %d-%d)", seq - args.start_seq,
                     args.start_seq, seq - 1)
    finally:
        if client:
            client.disconnect()


def run_device():
    """Run on actual M5Stack Core2 hardware (MicroPython)."""
    logger.info("Initializing M5Stack Core2 sensors...")
    # On real hardware, this would:
    # 1. Initialize I2S microphone
    # 2. Connect to WiFi
    # 3. Connect to MQTT broker
    # 4. Loop: read sensors -> extract_window() -> publish telemetry
    # For now, fall back to simulation
    logger.warning("Hardware mode not yet implemented — use --sim")


def parse_args():
    parser = argparse.ArgumentParser(description="Smart Space Pulse Device")
    parser.add_argument("--sim", action="store_true", help="Run in local simulation mode")
    parser.add_argument("--profile", choices=list(PROFILES.keys()), default="quiet",
                        help="Simulation profile (default: quiet)")
    parser.add_argument("--device", default="Core2Kit",
                        help="Device ID (must match Core2Kit*)")
    parser.add_argument("--location", default="library-1f",
                        help="Location ID (e.g. library-1f)")
    parser.add_argument("--host", default=MQTT_HOST,
                        help=f"MQTT broker host (default: {MQTT_HOST})")
    parser.add_argument("--port", type=int, default=MQTT_PORT,
                        help=f"MQTT broker port (default: {MQTT_PORT})")
    parser.add_argument("--duration", type=int, default=0,
                        help="Run duration in seconds (0 = until Ctrl-C)")
    parser.add_argument("--start-seq", type=int, default=1,
                        help="Starting sequence number (default: 1)")
    return parser.parse_args()


def main():
    args = parse_args()

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s.000Z [%(levelname)-5s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    if args.sim:
        simulate(args)
    else:
        run_device()


if __name__ == "__main__":
    main()
