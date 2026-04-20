"""
Tests for device/feature_extractor.py
"""
import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from device.feature_extractor import compute_spl, extract_window


def test_compute_spl_known_value():
    """SPL of amplitude 1.0 should be 0 dB (20*log10(1) = 0)."""
    result = compute_spl([1.0, 1.0, 1.0])
    assert math.isclose(result, 0.0, abs_tol=0.01)


def test_compute_spl_empty():
    assert compute_spl([]) == 0.0


def test_compute_spl_zero_samples():
    assert compute_spl([0.0, 0.0]) == 0.0


def test_extract_window_keys():
    result = extract_window([0.5, 0.6])
    assert "spl_db" in result
    assert "ts_utc" in result
    assert "accel_rms" not in result


def test_extract_window_values_positive():
    result = extract_window([10.0, 20.0])
    assert result["spl_db"] > 0
