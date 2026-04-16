"""
Tests for processing/windower.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from processing.windower import Windower


def _make_sample(seq: int, accel: float = 0.2, spl: float = 50.0,
                 location: str = "library-1f") -> dict:
    return {
        "device_id": "core2-a1b2",
        "location_id": location,
        "ts_utc": f"2026-04-17T14:20:{seq:02d}.000Z",
        "accel_rms": accel,
        "spl_db": spl,
        "seq": seq,
    }


def test_hysteresis_high_zone():
    """Score >= 65 → suitable."""
    w = Windower()
    assert w.apply_hysteresis(80.0, "loc-a") == "suitable"


def test_hysteresis_low_zone():
    """Score < 55 → not_suitable."""
    w = Windower()
    assert w.apply_hysteresis(40.0, "loc-a") == "not_suitable"


def test_hysteresis_dead_band_holds_previous():
    """Score in [55, 65) should hold previous state."""
    w = Windower()
    # First, set to suitable
    w.apply_hysteresis(70.0, "loc-a")
    # Now enter dead band — should hold suitable
    assert w.apply_hysteresis(60.0, "loc-a") == "suitable"


def test_hysteresis_dead_band_no_previous():
    """Score in [55, 65) with no previous state defaults to not_suitable."""
    w = Windower()
    assert w.apply_hysteresis(60.0, "loc-new") == "not_suitable"


def test_hysteresis_transition_from_suitable_to_not():
    w = Windower()
    w.apply_hysteresis(70.0, "loc-a")
    w.apply_hysteresis(60.0, "loc-a")  # dead band, hold
    result = w.apply_hysteresis(50.0, "loc-a")  # below 55
    assert result == "not_suitable"


def test_ingest_returns_none_before_window_full():
    w = Windower(window_size=30)
    for i in range(29):
        result = w.ingest(_make_sample(i))
        assert result is None


def test_ingest_returns_state_after_window():
    w = Windower(window_size=30)
    for i in range(29):
        w.ingest(_make_sample(i, accel=0.1, spl=40.0))
    result = w.ingest(_make_sample(29, accel=0.1, spl=40.0))
    # Low accel + low spl should give suitable
    assert result is not None
    assert "state" in result
    assert result["state"] == "suitable"
