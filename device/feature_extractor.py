"""
Smart Space Pulse — On-device Feature Extraction

Computes RMS acceleration (m/s²) and SPL audio (dB) over 1-second tumbling windows.
"""
import math
from datetime import datetime, timezone


def compute_rms_accel(samples: list[float]) -> float:
    """Compute RMS of 3-axis accelerometer samples.

    Args:
        samples: List of acceleration magnitude values (m/s²).

    Returns:
        RMS value in m/s².
    """
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


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


def extract_window(accel_buf: list[float], audio_buf: list[float], window_sec: int = 1) -> dict:
    """Extract features from a single time window.

    Args:
        accel_buf: Buffer of accelerometer samples for the window.
        audio_buf: Buffer of audio samples for the window.
        window_sec: Window duration in seconds (default 1).

    Returns:
        Dict with accel_rms, spl_db, and ts_utc.
    """
    return {
        "accel_rms": round(compute_rms_accel(accel_buf), 2),
        "spl_db": round(compute_spl(audio_buf), 2),
        "ts_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "000Z",
    }
