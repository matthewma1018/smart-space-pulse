"""
Smart Space Pulse — Replay Tool

Feeds recorded JSONL messages back through the processing pipeline.

Usage:
    python observability/replay.py \
      --file data_samples/recorded/rec_suit_000_sensor_log.jsonl \
      --speed 10 \
      --dry-run
"""
import argparse
import json
import sys
import time

sys.path.insert(0, ".")

from processing.windower import Windower


def parse_args():
    parser = argparse.ArgumentParser(description="Replay recorded MQTT messages")
    parser.add_argument("--file", required=True, help="Path to JSONL file to replay")
    parser.add_argument("--speed", type=float, default=1.0, help="Playback speed multiplier")
    parser.add_argument("--dry-run", action="store_true", help="Skip the inter-message sleep; replay as fast as possible")
    return parser.parse_args()


def main():
    args = parse_args()
    windower = Windower()

    with open(args.file, "r") as f:
        messages = [json.loads(line) for line in f if line.strip()]

    print(f"[REPLAY] Loaded {len(messages)} messages from {args.file}")
    print(f"[REPLAY] Speed: {args.speed}x | Dry-run: {args.dry_run}")

    prev_ts = None
    for msg in messages:
        if not args.dry_run and prev_ts is not None:
            delay = 1.0 / args.speed
            time.sleep(delay)

        result = windower.ingest(msg)
        if result:
            print(f"[REPLAY] State change: {result['location_id']} "
                  f"{result['prev_state']} -> {result['state']} (score={result['score']})")

        prev_ts = msg.get("ts_utc")

    print(f"[REPLAY] Done. Processed {len(messages)} messages.")


if __name__ == "__main__":
    main()
