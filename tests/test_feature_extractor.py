"""
Tests for device/feature_extractor.py
"""
import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from device.feature_extractor import compute_rms_accel, compute_spl, extract_window


def test_compute_rms_accel_known_value():
    """RMS of [3, 4] should be 5.0"""
    assert compute_rms_accel([3.0, 4.0]) == 5.0


def test_compute_rms_accel_zero():
    assert compute_rms_accel([0.0, 0.0]) == 0.0


def test_compute_rms_accel_empty():
    assert compute_rms_accel([]) == 0.0


def test_compute_rms_accel_single():
    assert compute_rms_accel([2.0]) == 2.0


def test_compute_spl_known_value():
    """SPL of amplitude 1.0 should be 0 dB (20*log10(1) = 0)."""
    result = compute_spl([1.0, 1.0, 1.0])
    assert math.isclose(result, 0.0, abs_tol=0.01)


def test_compute_spl_empty():
    assert compute_spl([]) == 0.0


def test_compute_spl_zero_samples():
    assert compute_spl([0.0, 0.0]) == 0.0


def test_extract_window_keys():
    result = extract_window([0.1, 0.2], [0.5, 0.6])
    assert "accel_rms" in result
    assert "spl_db" in result
    assert "ts_utc" in result


def test_extract_window_values_positive():
    result = extract_window([0.3, 0.4], [10.0, 20.0])
    assert result["accel_rms"] > 0
    assert result["spl_db"] > 0
