"""
Smart Space Pulse — Edge Policy (On-device Fallback Rules)

Lightweight rules for when network is unavailable.
No ML inference — pure threshold-based classification.
"""

LOUD_THRESHOLD_DB: float = 75.0   # dB SPL


def classify(spl_db: float) -> str:
    """Classify occupancy state using simple threshold.

    Args:
        spl_db: Sound pressure level in dB.

    Returns:
        "busy" if threshold exceeded, "quiet" otherwise.
    """
    if spl_db > LOUD_THRESHOLD_DB:
        return "busy"
    return "quiet"
