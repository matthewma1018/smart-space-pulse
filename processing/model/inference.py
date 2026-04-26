"""
Smart Space Pulse — Inference Module

Exposes two scoring entry points:

  score(feature_vector)        — rule-based only; takes a 5-element window-level
                                 feature vector. Used for tests and as the
                                 ultimate fallback.
  score_from_samples(spl_list) — LSTM-first; takes the 30 raw SPL values from
                                 a window, builds per-timestep rolling features,
                                 and runs them through the trained LSTM. Falls
                                 back to rule-based if LSTM weights aren't
                                 available.

Keeping the two paths separate lets callers choose the abstraction level
without the inference layer having to guess what the input represents.
"""
import logging
import os

logger = logging.getLogger("inference")

IDX_SPL_MEAN = 0
IDX_SPL_STD = 1
IDX_SPL_P90 = 2
IDX_SPL_MAX = 3
IDX_SPL_SPIKE_COUNT = 4

INPUT_FEATURES = 5
ROLLING_SUB_WINDOW = 8  # must match train.py


def _window_features(spl: list[float]) -> list[float]:
    """Window-level 5-feature vector (mean/std/p90/max/spike_count)."""
    n = len(spl)
    mean = sum(spl) / n
    std = (sum((x - mean) ** 2 for x in spl) / n) ** 0.5
    p90 = sorted(spl)[min(int(0.9 * n), n - 1)]
    mx = max(spl)
    if std < 1e-6:
        spikes = 0
    else:
        thresh = mean + 1.5 * std
        spikes = sum(1 for x in spl if x > thresh)
    return [mean, std, p90, mx, float(spikes)]


def _per_timestep_features(spl: list[float],
                           sub_window: int = ROLLING_SUB_WINDOW) -> list[list[float]]:
    """Same rolling-sub-window features the LSTM was trained on."""
    features = []
    for t in range(len(spl)):
        lo = max(0, t - sub_window + 1)
        w = spl[lo:t + 1]
        n = len(w)
        mean = sum(w) / n
        std = (sum((x - mean) ** 2 for x in w) / n) ** 0.5
        sw = sorted(w)
        p90 = sw[min(int(0.9 * n), n - 1)]
        mx = max(w)
        if std < 1e-6:
            spikes = 0
        else:
            thresh = mean + 1.5 * std
            spikes = sum(1 for x in w if x > thresh)
        features.append([mean, std, p90, mx, float(spikes)])
    return features


def _rule_based_score(feature_vector: list[float]) -> float:
    """Deterministic rule-based scorer.

    Args:
        feature_vector: 5-element list
            [spl_mean, spl_std, spl_p90, spl_max, spl_spike_count]

    Returns:
        Score in range 0-100 (higher = more suitable).
    """
    spl_mean = feature_vector[IDX_SPL_MEAN]
    spl_p90 = feature_vector[IDX_SPL_P90]
    spikes = feature_vector[IDX_SPL_SPIKE_COUNT]

    if spl_mean < 55:
        noise_score = 0
    elif spl_mean < 70:
        noise_score = (spl_mean - 55) / 15.0 * 50
    else:
        noise_score = 50 + (spl_mean - 70) / 30.0 * 30

    spike_score = max(0, (spl_p90 - 75) / 25.0) * 20
    burst_score = min(spikes, 8) / 8.0 * 10

    s = 100.0 - noise_score - spike_score - burst_score
    return max(0.0, min(100.0, s))


_model = None
_model_loaded = False

_logistic = None
_logistic_loaded = False


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


def _load_logistic():
    global _logistic, _logistic_loaded
    _logistic_loaded = True
    path = os.getenv("LOGISTIC_MODEL_PATH", "processing/model/logistic_model.joblib")
    if os.path.exists(path):
        try:
            import joblib
            _logistic = joblib.load(path)
            logger.info("Loaded logistic model from %s", path)
        except Exception:
            logger.warning("Failed to load logistic model", exc_info=True)
    else:
        logger.info("No logistic model found at %s", path)
    return _logistic


def score(feature_vector: list[float]) -> float:
    """Rule-based score of a 5-element window-level feature vector.

    This is deterministic and does not touch the LSTM — used for tests and
    as the fallback path. For LSTM-powered scoring, use score_from_samples.
    """
    return _rule_based_score(feature_vector)


def score_from_samples(spl_samples: list[float]) -> float:
    """LSTM score of a 30-sample SPL window; rule-based fallback otherwise.

    Args:
        spl_samples: Raw SPL values from a single 30-sample window.

    Returns:
        Float score in [0, 100]. Higher = more suitable.
    """
    global _model
    if not _model_loaded:
        _load_model()

    if _model is not None:
        import torch
        per_step = _per_timestep_features(spl_samples)
        with torch.no_grad():
            x = torch.tensor(per_step, dtype=torch.float32).unsqueeze(0)  # (1, 30, 5)
            prob_suitable = float(_model(x).item())
            return max(0.0, min(100.0, prob_suitable * 100.0))

    return _rule_based_score(_window_features(spl_samples))


def score_logistic_from_samples(spl_samples: list[float]) -> float | None:
    """Logistic regression score of a 30-sample SPL window.

    Returns:
        Float score in [0, 100] (higher = more suitable), or None if model unavailable.
    """
    global _logistic, _logistic_loaded
    if not _logistic_loaded:
        _load_logistic()
    if _logistic is None:
        return None
    features = [_window_features(spl_samples)]
    X = _logistic["scaler"].transform(features)
    prob = float(_logistic["model"].predict_proba(X)[0][1])
    return max(0.0, min(100.0, prob * 100.0))
