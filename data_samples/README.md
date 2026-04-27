# Data Samples

Labeled SPL windows used for training and offline replay. Two classes —
`suit` (suitable for quiet work) and `notsuit` (too noisy) — split across
recorded data captured from a real Core2 device and synthetic data generated
to amplify the dataset.

## File format

One JSONL file = **one 30-sample window**. Each line is a single 1 Hz reading:

```json
{"ts_utc": "2026-04-18T19:28:54Z", "device_id": "core2-device2", "location_id": "library", "spl_db": 50.43}
```

| Field | Type | Unit / format |
|-------|------|---------------|
| `ts_utc` | string | ISO 8601 UTC, `Z` suffix |
| `device_id` | string | Source device identifier |
| `location_id` | string | Logical space the device is monitoring |
| `spl_db` | float | Sound pressure level, **decibels (dB SPL)**, A-weighted approximation derived from the Core2 mic; range ~30–110 dB |

**Sampling rate:** 1 Hz (one reading per second). 30 samples per file = a
30-second window — the exact window size the LSTM and logistic models are
trained on.

## Filename convention

```
{source}_{label}_{index:03d}_sensor_log.jsonl
```

| Token | Values |
|-------|--------|
| `source` | `rec` (recorded from real device), `syn` (synthetically generated) |
| `label` | `suit` (suitable / quiet), `notsuit` (not suitable / noisy) |
| `index` | Zero-padded sequence number within the (source, label) bucket |

The label is the **window-level ground truth** — the entire 30-sample window
belongs to that class.

## Counts

| Source | suit | notsuit | total |
|--------|------|---------|-------|
| recorded (`rec_*`) | 50 | 20 | 70 |
| synthetic (`syn_*`) | 250 | 290 | 540 |
| **combined** | 300 | 310 | **610** |

Approximately balanced once recorded and synthetic are pooled.

## Loading

```python
import json
from pathlib import Path

def load_window(path: Path) -> tuple[list[float], str]:
    """Returns (30 spl_db values, label)."""
    samples = [json.loads(line)["spl_db"] for line in path.read_text().splitlines() if line.strip()]
    label = "suitable" if "_suit_" in path.name and "_notsuit_" not in path.name else "not_suitable"
    return samples, label

windows = [load_window(p) for p in Path("data_samples/recorded").glob("*.jsonl")]
```

The training pipeline (`processing/model/train.py`,
`processing/model/train_logistic.py`) loads these directly. The replay tool
(`observability/replay.py`) can stream them through the live pipeline as if
they were arriving from a real device.

## How the synthetic data was generated

`processing/model/generate_synthetic.py` perturbs recorded windows with
parametric noise (gain shifts, additive jitter, occasional spikes) to expand
coverage of the decision boundary. See that script for the exact parameters.

## Notes

- Sample data is for offline training and replay only — it is not pushed
  through the live MQTT schema validator (`messaging/schema.md`), so its
  field values do not need to match the live regex.
- Timestamps are wall-clock from the capture session and are useful for
  ordering within a window but not across windows.
