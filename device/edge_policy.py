"""
Smart Space Pulse — Edge Policy (On-device Fallback Rules)

Lightweight rules for when network is unavailable.
No ML inference — pure threshold-based classification.
"""

LOUD_THRESHOLD_DB: float = 75.0   # dB SPL
MOTION_THRESHOLD: float = 0.5     # m/s²


def classify(accel_rms: float, spl_db: float) -> str:
    """Classify occupancy state using simple thresholds.

    Args:
        accel_rms: RMS acceleration in m/s².
        spl_db: Sound pressure level in dB.

    Returns:
        "busy" if both thresholds exceeded, "quiet" otherwise.
    """
    if spl_db > LOUD_THRESHOLD_DB and accel_rms > MOTION_THRESHOLD:
        return "busy"
    return "quiet"
