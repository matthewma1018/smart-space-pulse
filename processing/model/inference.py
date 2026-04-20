"""
Smart Space Pulse — Inference Module

Loads model weights and exposes a score() function.
Includes a rule-based fallback when no trained weights are available.
"""
import logging
import os
import sys

logger = logging.getLogger("inference")

# Feature vector indices
IDX_SPL_MEAN = 0
IDX_SPL_STD = 1
IDX_SPL_P90 = 2
IDX_SPL_MAX = 3

INPUT_FEATURES = 4


def _rule_based_score(feature_vector: list[float]) -> float:
    """Deterministic rule-based scorer (fallback when no LSTM weights available).

    Logic:
        - Lower noise → higher suitability score.
        - Score mapped to 0–100 range.

    Args:
        feature_vector: 4-element list [spl_mean, spl_std, spl_p90, spl_max]

    Returns:
        Score in range 0–100.
    """
    spl_mean = feature_vector[IDX_SPL_MEAN]
    spl_std = feature_vector[IDX_SPL_STD]
    spl_p90 = feature_vector[IDX_SPL_P90]

    # Noise penalty: quiet < 55 dB is good, 55-70 moderate, >70 bad
    if spl_mean < 55:
        noise_score = 0
    elif spl_mean < 70:
        noise_score = (spl_mean - 55) / 15.0 * 50
    else:
        noise_score = 50 + (spl_mean - 70) / 30.0 * 30

    # Spike penalty: sudden loud bursts above 75 dB
    spike_score = max(0, (spl_p90 - 75) / 25.0) * 20

    score = 100.0 - noise_score - spike_score
    return max(0.0, min(100.0, score))


_model = None
_model_loaded = False


def _load_model():
    """Attempt to load LSTM weights. Returns None if unavailable."""
    global _model, _model_loaded
    _model_loaded = True
    weights_path = os.getenv("MODEL_WEIGHTS_PATH", "processing/model/lstm_weights.pt")
    if os.path.exists(weights_path):
        try:
            import torch
            from processing.model.train import OccupancyLSTM
            model = OccupancyLSTM(input_size=INPUT_FEATURES)
            model.load_state_dict(torch.load(weights_path, map_location="cpu", weights_only=True))
            model.eval()
            _model = model
            logger.info("Loaded LSTM weights from %s", weights_path)
        except Exception:
            logger.warning("Failed to load LSTM weights — falling back to rule-based scorer",
                           exc_info=True)
            _model = None
    else:
        logger.info("No LSTM weights found — using rule-based scorer")
    return _model


def score(feature_vector: list[float]) -> float:
    """Score a feature vector, returning suitability 0–100.

    Uses LSTM if weights are available, otherwise falls back to rule-based.

    Args:
        feature_vector: 4-element feature list.

    Returns:
        Float score in [0, 100].
    """
    global _model
    if not _model_loaded:
        _load_model()

    if _model is not None:
        import torch
        with torch.no_grad():
            x = torch.tensor([feature_vector], dtype=torch.float32)
            x = x.unsqueeze(0)  # (1, 1, 4) — batch=1, seq_len=1, features=4
            result = _model(x)
            raw = float(result.item())
            return max(0.0, min(100.0, raw))

    return _rule_based_score(feature_vector)
