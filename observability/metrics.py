"""
Smart Space Pulse — Metrics Module

Tracks latency, throughput, and error counters.
"""
import time
from collections import defaultdict

_metrics: dict[str, float | int] = defaultdict(float)


def increment(name: str, value: int = 1) -> None:
    """Increment a counter metric."""
    _metrics[name] = _metrics.get(name, 0) + value


def observe(name: str, value: float) -> None:
    """Record a histogram observation."""
    key_sum = f"{name}_sum"
    key_count = f"{name}_count"
    _metrics[key_sum] = _metrics.get(key_sum, 0.0) + value
    _metrics[key_count] = _metrics.get(key_count, 0) + 1


def timer(name: str):
    """Context manager to measure elapsed time."""
    class _Timer:
        def __enter__(self):
            self.start = time.monotonic()
            return self

        def __exit__(self, *args):
            elapsed_ms = (time.monotonic() - self.start) * 1000
            observe(name, elapsed_ms)

    return _Timer()


def snapshot() -> dict:
    """Return a snapshot of all current metrics."""
    return dict(_metrics)
