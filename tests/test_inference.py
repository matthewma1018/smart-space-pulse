"""
Tests for processing/model/inference.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from processing.model.inference import score


def test_score_returns_float():
    result = score([50.0, 5.0, 55.0, 60.0])
    assert isinstance(result, float)


def test_score_in_range():
    """Score must be between 0 and 100."""
    result = score([50.0, 5.0, 55.0, 60.0])
    assert 0.0 <= result <= 100.0


def test_low_noise_high_score():
    """Low noise should give a high suitability score."""
    quiet = score([35.0, 2.0, 40.0, 42.0])
    loud = score([80.0, 10.0, 90.0, 95.0])
    assert quiet > loud


def test_high_noise_low_score():
    """High noise should give a low score."""
    result = score([85.0, 12.0, 92.0, 98.0])
    assert result < 50.0


def test_rule_based_deterministic():
    """Same input should always produce same output."""
    features = [55.0, 8.0, 62.0, 65.0]
    assert score(features) == score(features)
