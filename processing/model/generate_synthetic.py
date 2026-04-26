"""
Smart Space Pulse — Synthetic Data Amplifier

Amplifies the manually recorded dataset (data_samples/recorded/) by treating
each recorded window as a seed and resynthesising perturbed copies under a
target acoustic profile (quiet ambient or loud event).

Output: data_samples/synthetic/
    syn_suit_NNN_sensor_log.jsonl      (250 windows, quiet profile)
    syn_notsuit_NNN_sensor_log.jsonl   (290 windows, loud profile)

Usage:
    python -m processing.model.generate_synthetic
"""
import argparse
import glob
import json
import logging
import math
import os
import random
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

logger = logging.getLogger("generate_synthetic")

WINDOW_SIZE = 30


def load_recorded_windows(recorded_dir: str) -> list[list[float]]:
    """Load all 30-sample windows from the recorded dataset as augmentation seeds."""
    windows = []
    for path in sorted(glob.glob(os.path.join(recorded_dir, "*.jsonl"))):
        spl = []
        with open(path) as f:
            for line in f:
                try:
                    v = json.loads(line).get("spl_db")
                    if isinstance(v, (int, float)) and v > 10.0:
                        spl.append(float(v))
                except json.JSONDecodeError:
                    continue
        if len(spl) == WINDOW_SIZE:
            windows.append(spl)
    logger.info("Loaded %d recorded windows from %s", len(windows), recorded_dir)
    return windows


def make_quiet_window(seed: list[float]) -> list[float]:
    """Resynthesise a seed into a quiet ambient profile (mean ~42-55 dB)."""
    n = len(seed)
    target_mean  = random.uniform(42.0, 55.0)
    shift        = target_mean - sum(seed) / n
    drift_amp    = random.uniform(0.5, 2.0)
    drift_period = random.uniform(20.0, 40.0)
    drift_phase  = random.uniform(0.0, 6.28)
    out = []
    for t, s in enumerate(seed):
        drift = drift_amp * math.sin(2 * math.pi * t / drift_period + drift_phase)
        v = s + shift + drift + random.gauss(0.0, 0.8)
        if random.random() < 0.05:
            v += random.uniform(3.0, 8.0)
        out.append(round(max(30.0, min(110.0, v)), 2))
    return out


def make_loud_window(seed: list[float]) -> list[float]:
    """Resynthesise a seed into a loud / event profile (mean ~60-78 dB)."""
    n = len(seed)
    target_mean  = random.uniform(60.0, 78.0)
    shift        = target_mean - sum(seed) / n
    drift_amp    = random.uniform(1.5, 4.0)
    drift_period = random.uniform(15.0, 35.0)
    drift_phase  = random.uniform(0.0, 6.28)
    out = []
    for t, s in enumerate(seed):
        drift = drift_amp * math.sin(2 * math.pi * t / drift_period + drift_phase)
        v = s + shift + drift + random.gauss(0.0, 1.2)
        if random.random() < 0.30:
            v += random.uniform(6.0, 20.0)
        out.append(round(max(30.0, min(110.0, v)), 2))
    return out


def write_window_jsonl(path, spl, device_id, location_id, start_ts):
    with open(path, "w") as f:
        for i, v in enumerate(spl):
            ts = start_ts + timedelta(seconds=i)
            f.write(json.dumps({
                "ts_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "device_id": device_id,
                "location_id": location_id,
                "spl_db": v,
            }) + "\n")


def random_start_ts() -> datetime:
    """Random reasonable daytime start across 2026-04-21 to 2026-04-25."""
    day    = random.choice([21, 22, 23, 24, 25])
    hour   = random.randint(7, 21)
    minute = random.randint(0, 59)
    second = random.randint(0, 29)
    return datetime(2026, 4, day, hour, minute, second, tzinfo=timezone.utc)


def generate(output_root: str, seed: int) -> None:
    random.seed(seed)

    recorded_dir  = os.path.join(output_root, "recorded")
    synthetic_dir = os.path.join(output_root, "synthetic")
    os.makedirs(synthetic_dir, exist_ok=True)

    seeds = load_recorded_windows(recorded_dir)
    if not seeds:
        raise RuntimeError(
            f"No recorded windows found in {recorded_dir}. "
            "Populate data_samples/recorded/ with labelled JSONL windows first."
        )

    for i in range(250):
        spl  = make_quiet_window(random.choice(seeds))
        path = os.path.join(synthetic_dir, f"syn_suit_{i:03d}_sensor_log.jsonl")
        write_window_jsonl(path, spl, "core2-device2", "library", random_start_ts())

    for i in range(290):
        spl  = make_loud_window(random.choice(seeds))
        path = os.path.join(synthetic_dir, f"syn_notsuit_{i:03d}_sensor_log.jsonl")
        write_window_jsonl(path, spl, "core2-device2", "library", random_start_ts())

    logger.info("Wrote 250 suitable + 290 not-suitable to %s", synthetic_dir)


def parse_args():
    p = argparse.ArgumentParser(description="Amplify recorded dataset into synthetic training windows")
    p.add_argument("--output-root", default="data_samples")
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.000Z [%(levelname)-5s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    generate(**vars(parse_args()))


if __name__ == "__main__":
    main()
