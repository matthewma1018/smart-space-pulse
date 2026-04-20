"""
Smart Space Pulse — On-device Feature Extraction

Computes SPL audio (dB) over 1-second tumbling windows.
"""
import math
from datetime import datetime, timezone


def compute_spl(samples: list[float]) -> float:
    """Compute Sound Pressure Level in dB from raw audio samples.

    Args:
        samples: List of raw audio amplitude values.

    Returns:
        SPL value in dB.
    """
    if not samples:
        return 0.0
    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
    if rms <= 0:
        return 0.0
    return 20.0 * math.log10(rms)


def extract_window(audio_buf: list[float], window_sec: int = 1) -> dict:
    """Extract features from a single time window.

    Args:
        audio_buf: Buffer of audio samples for the window.
        window_sec: Window duration in seconds (default 1).

    Returns:
        Dict with spl_db and ts_utc.
    """
    return {
        "spl_db": round(compute_spl(audio_buf), 2),
        "ts_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "000Z",
    }
