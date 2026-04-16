"""
Smart Space Pulse — Inference Module

Loads model weights and exposes a score() function.
Includes a rule-based fallback when no trained weights are available.
"""
import logging
import os

logger = logging.getLogger("inference")

# Feature vector indices
IDX_ACCEL_MEAN = 0
IDX_ACCEL_STD = 1
IDX_SPL_MEAN = 2
IDX_SPL_STD = 3
IDX_SPL_P90 = 4
IDX_SPL_MAX = 5


def _rule_based_score(feature_vector: list[float]) -> float:
    """Deterministic rule-based scorer (fallback when no LSTM weights available).

    Logic:
        - Lower noise + lower motion → higher suitability score.
        - Score mapped to 0–100 range.

    Args:
        feature_vector: 6-element list [accel_rms_mean, accel_rms_std,
                         spl_mean, spl_std, spl_p90, spl_max]

    Returns:
        Score in range 0–100.
    """
    accel_mean = feature_vector[IDX_ACCEL_MEAN]
    spl_mean = feature_vector[IDX_SPL_MEAN]
    spl_p90 = feature_vector[IDX_SPL_P90]

    # Penalize high motion and noise
    motion_penalty = min(accel_mean / 2.0, 1.0) * 40
    noise_penalty = min(spl_mean / 100.0, 1.0) * 40
    spike_penalty = max(0, (spl_p90 - 70) / 30.0) * 20

    score = 100.0 - motion_penalty - noise_penalty - spike_penalty
    return max(0.0, min(100.0, score))


_model = None


def _load_model():
    """Attempt to load LSTM weights. Returns None if unavailable."""
    global _model
    weights_path = os.getenv("MODEL_WEIGHTS_PATH", "processing/model/lstm_weights.pt")
    if os.path.exists(weights_path):
        logger.info("Loading LSTM weights from %s", weights_path)
        # TODO: load PyTorch model
        _model = None
    else:
        logger.info("No LSTM weights found — using rule-based scorer")
        _model = None
    return _model


def score(feature_vector: list[float]) -> float:
    """Score a feature vector, returning suitability 0–100.

    Uses LSTM if weights are available, otherwise falls back to rule-based.

    Args:
        feature_vector: 6-element feature list.

    Returns:
        Float score in [0, 100].
    """
    global _model
    if _model is not None:
        # TODO: run LSTM inference
        pass

    return _rule_based_score(feature_vector)
