"""
Smart Space Pulse — Windower

Collects 30 consecutive telemetry samples per location_id, builds feature vectors,
runs inference, and applies hysteresis decision policy.
"""
import logging
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger("windower")

WINDOW_SIZE = 30
SCORE_HIGH_THRESHOLD = 65
SCORE_LOW_THRESHOLD = 55


class Windower:
    """Aggregates telemetry into windows and applies hysteresis scoring."""

    def __init__(self, window_size: int = WINDOW_SIZE):
        self.window_size = window_size
        self.buffers: dict[str, list[dict]] = defaultdict(list)
        self.states: dict[str, str] = {}

    def _build_feature_vector(self, samples: list[dict]) -> list[float]:
        """Build 5-element feature vector from a window of samples.

        Returns: [spl_mean, spl_std, spl_p90, spl_max, spl_spike_count]

        spl_spike_count is the number of samples exceeding mean + 1.5*std —
        a ZCR-like burstiness proxy since we only see 1 Hz SPL, not raw audio.
        """
        spl = [s["spl_db"] for s in samples]

        n = len(samples)
        spl_mean = sum(spl) / n
        spl_std = (sum((x - spl_mean) ** 2 for x in spl) / n) ** 0.5

        sorted_spl = sorted(spl)
        p90_idx = int(0.9 * n)
        spl_p90 = sorted_spl[min(p90_idx, n - 1)]
        spl_max = max(spl)

        if spl_std < 1e-6:
            spl_spike_count = 0
        else:
            thresh = spl_mean + 1.5 * spl_std
            spl_spike_count = sum(1 for x in spl if x > thresh)

        return [spl_mean, spl_std, spl_p90, spl_max, float(spl_spike_count)]

    def apply_hysteresis(self, score: float, location_id: str) -> str:
        """Apply hysteresis decision policy.

        Args:
            score: Model output score (0–100).
            location_id: Location to look up previous state.

        Returns:
            New state string.
        """
        prev = self.states.get(location_id)
        if score >= SCORE_HIGH_THRESHOLD:
            new_state = "suitable"
        elif score < SCORE_LOW_THRESHOLD:
            new_state = "not_suitable"
        else:
            new_state = prev if prev else "not_suitable"

        self.states[location_id] = new_state
        return new_state

    def ingest(self, sample: dict) -> dict | None:
        """Add a sample to the buffer and process if window is full.

        Args:
            sample: Telemetry dict with spl_db, location_id, ts_utc, etc.

        Returns:
            State-change dict if a state transition occurred, else None.
        """
        location_id = sample["location_id"]
        self.buffers[location_id].append(sample)

        if len(self.buffers[location_id]) >= self.window_size:
            window = self.buffers[location_id][:self.window_size]
            self.buffers[location_id] = self.buffers[location_id][self.window_size:]

            # LSTM was trained on per-timestep rolling features over the raw
            # SPL sequence; pass samples so inference can build that shape.
            from processing.model.inference import score_from_samples
            spl_samples = [s["spl_db"] for s in window]
            raw_score = score_from_samples(spl_samples)

            prev_state = self.states.get(location_id, "not_suitable")
            new_state = self.apply_hysteresis(raw_score, location_id)
            changed = new_state != prev_state

            logger.info("location=%s score=%.1f state=%s%s",
                        location_id, raw_score, new_state,
                        " (changed)" if changed else "")

            return {
                "device_id": sample["device_id"],
                "location_id": location_id,
                "ts_utc": sample["ts_utc"],
                "score": round(raw_score, 1),
                "state": new_state,
                "prev_state": prev_state,
                "window_sec": self.window_size,
                "changed": changed,
            }
        return None


if __name__ == "__main__":
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s.000Z [%(levelname)-5s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    logger.info("Windower started (window_size=%d)", WINDOW_SIZE)
