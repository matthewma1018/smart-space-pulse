# CLAUDE.md — Smart Space Pulse: Tracking Human Activity with Sensors

> **For Claude Code:** This file is the canonical initialization guide for this project.
> Read it in full before touching any file. Every section maps to a required deliverable.
> Do not commit secrets. Do not skip the schema contracts. Follow the directory layout exactly.

---

## 1. Project Overview

**Smart Space Pulse** is an AIoT system that monitors occupancy and noise levels in shared spaces
(libraries, coworking offices, airport lounges, internet cafes) using M5Stack Core2 edge devices,
an MQTT broker, a Python cloud processor, and a real-time dashboard.

### Architecture in one sentence

> Core2 devices stream 1 summary message/second over MQTT → a Python processor windows 30 samples
> → an LSTM classifier scores each location 0–100 → the dashboard shows occupancy state with
> hysteresis (≥ 65 = Suitable, < 55 = Not Suitable).

### Key design decisions

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Edge summarization | RMS accel (m/s²) + SPL audio (dB) | Privacy (no raw audio off-device), bandwidth reduction |
| Transport | MQTT QoS 1, retain=false | At-least-once delivery; broker handles fan-out |
| ML model | LSTM (server-side) | Sequential 30-step windows; easy iteration without reflashing firmware |
| Decision policy | Hysteresis band 55/65 | Prevents state flickering on borderline readings |

---

## 2. Repository Layout

```
smart-space-pulse/
├── CLAUDE.md                   ← you are here
├── README.md                   ← human quick-start (auto-generated from this file's §3)
├── .env.example                ← all env vars, no real values
├── .gitignore
│
├── device/                     ← Deliverable 2: Core2 firmware
│   ├── main.py                 ← UIFlow / MicroPython entry point
│   ├── feature_extractor.py    ← windowing, RMS, SPL
│   ├── edge_policy.py          ← on-device rules / lightweight MLP fallback
│   ├── display.py              ← LCD / LED / buzzer logic
│   ├── serial_logger.py        ← UART debug output
│   └── FIRMWARE_NOTES.md       ← UIFlow version, flash instructions
│
├── messaging/                  ← Deliverable 3: MQTT schema
│   ├── schema.md               ← topic hierarchy + field contracts
│   └── examples/
│       ├── telemetry_sample.json
│       └── alert_sample.json
│
├── processing/                 ← Deliverable 4: cloud pipeline
│   ├── ingestor.py             ← MQTT subscriber → raw store
│   ├── windower.py             ← 30-second aggregation
│   ├── model/
│   │   ├── train.py
│   │   ├── inference.py
│   │   └── lstm_weights.pt     ← tracked via Git LFS or excluded; see §7
│   ├── storage.py              ← write to InfluxDB / SQLite / CSV
│   └── notebooks/
│       └── exploration.ipynb   ← time-series plots, histograms
│
├── visualization/              ← Deliverable 4 (cont.)
│   ├── dashboard.py            ← Grafana provisioning OR Streamlit app
│   └── grafana/
│       └── dashboard.json      ← exported Grafana panel config
│
├── config/                     ← Deliverable 5: configuration
│   ├── .env.example
│   ├── iam_policy.json.example ← redacted AWS/GCP IAM sample
│   └── certs/
│       └── README_CERTS.md     ← how to generate & rotate TLS certs
│
├── observability/              ← Deliverable 6
│   ├── metrics.py              ← latency, throughput, error counters
│   ├── replay.py               ← feed recorded samples back through pipeline
│   └── sample_logs/
│       ├── success.log
│       └── failure.log
│
├── data_samples/               ← Deliverable 7
│   ├── sensor_readings.csv
│   ├── mqtt_messages.jsonl
│   └── DATA_DICTIONARY.md      ← units, sampling rates, column definitions
│
├── results/                    ← Deliverable 8
│   └── report.md               ← 2–3 page KPI report
│
└── tests/
    ├── test_feature_extractor.py
    ├── test_windower.py
    ├── test_inference.py
    └── test_mqtt_schema.py
```

**Naming rules Claude Code must follow:**
- Snake_case for all Python files and directories.
- No spaces in filenames anywhere in the repo.
- Never create files named `secrets.py`, `credentials.json`, or any variant — use `.env` loaded
  via `python-dotenv` or equivalent.

---

## 3. README (Root) — Content Contract

When generating or updating `README.md`, include exactly these sections in order:

```markdown
# Smart Space Pulse

## Overview
## Prerequisites
## Environment Setup
## Quick Start
### 1. Flash Device Firmware
### 2. Start the MQTT Broker
### 3. Run the Cloud Processor
### 4. Launch the Dashboard
## Run Commands Reference
## Troubleshooting
```

**Run commands to document:**

| Component | Command |
|-----------|---------|
| Device (local sim) | `python device/main.py --sim` |
| MQTT broker (Docker) | `docker compose up broker` |
| Ingestor | `python processing/ingestor.py` |
| Windower + inference | `python processing/windower.py` |
| Dashboard (Streamlit) | `streamlit run visualization/dashboard.py` |
| Replay test | `python observability/replay.py --file data_samples/mqtt_messages.jsonl` |
| Unit tests | `pytest tests/ -v` |

---

## 4. Device Code (Core2) — Deliverable 2

### Sensor pipeline

```
Raw accelerometer (±8 g, ~100 Hz)  →  RMS over N samples  →  float (m/s²)
Raw microphone (PDM/analog)        →  RMS → 20·log10(·)  →  float dB SPL
```

Both values are computed in a **1-second tumbling window** on-device before being packaged
into the outbound MQTT payload.

### Files to implement

**`device/feature_extractor.py`**
```python
# Must expose:
def compute_rms_accel(samples: list[float]) -> float: ...   # returns m/s²
def compute_spl(samples: list[float]) -> float: ...         # returns dB SPL
def extract_window(accel_buf, audio_buf, window_sec=1) -> dict: ...
# Returns: {"accel_rms": float, "spl_db": float, "ts_utc": str}
```

**`device/edge_policy.py`**
```python
# Lightweight on-device fallback rules (no network needed):
# If SPL > LOUD_THRESHOLD_DB and accel_rms > MOTION_THRESHOLD: state = "busy"
# Configurable via constants at top of file; thresholds loaded from .env or hardcoded defaults.
LOUD_THRESHOLD_DB   = 75.0   # dB
MOTION_THRESHOLD    = 0.5    # m/s²
```

**`device/display.py`**
- LCD: show current state ("Suitable" / "Not Suitable"), score, SPL, accel_rms.
- LED bar: green (≥65), amber (55–64), red (<55).
- Buzzer: single chirp on state transition only (not continuous).

**`device/serial_logger.py`**
- Log every published message to UART at 115200 baud.
- Format: `[ISO8601] TOPIC | JSON_PAYLOAD`

**`device/FIRMWARE_NOTES.md`** must document:
- UIFlow version used (v2.x preferred).
- How to flash via M5Burner.
- Which Core2 pins are used for I²S / PDM mic.
- How to enable serial monitoring (`screen /dev/ttyUSB0 115200`).

---

## 5. Messaging & Schema — Deliverable 3

### MQTT topic hierarchy

```
ssp/                              # Smart Space Pulse root
  {location_id}/                  # e.g. "library-1f", "lounge-jfk-b"
    telemetry                     # 1 Hz sensor summaries  (QoS 1, retain=false)
    state                         # occupancy state changes (QoS 1, retain=true)
    alert                         # threshold breach alerts (QoS 1, retain=false)
    heartbeat                     # device liveness ping    (QoS 0, retain=false)
```

### Telemetry payload (publish every 1 second)

```json
{
  "device_id":   "core2-a1b2",
  "location_id": "library-1f",
  "ts_utc":      "2026-04-17T14:23:01.000Z",
  "accel_rms":   0.32,
  "spl_db":      61.4,
  "seq":         4201
}
```

### State-change payload

```json
{
  "device_id":   "core2-a1b2",
  "location_id": "library-1f",
  "ts_utc":      "2026-04-17T14:23:30.000Z",
  "score":       67,
  "state":       "suitable",
  "prev_state":  "not_suitable",
  "window_sec":  30
}
```

### Alert payload

```json
{
  "device_id":   "core2-a1b2",
  "location_id": "library-1f",
  "ts_utc":      "2026-04-17T14:25:00.000Z",
  "alert_type":  "noise_spike",
  "spl_db":      88.2,
  "threshold_db": 75.0
}
```

**Schema rules Claude Code must enforce in `tests/test_mqtt_schema.py`:**
- `ts_utc` must be ISO 8601 with `Z` suffix (UTC only — no local offsets).
- `device_id` format: `core2-[a-z0-9]{4}`.
- All numeric fields must be `float`, never `null`.
- `state` must be one of `["suitable", "not_suitable", "transitioning"]`.

---

## 6. Processing / Storage / Visualization — Deliverable 4

### Ingestor (`processing/ingestor.py`)

- Subscribe to `ssp/#` with QoS 1.
- Validate schema (raise + log on failure, do not crash).
- Write raw messages to append-only storage (InfluxDB line protocol **or** SQLite `raw_telemetry`
  table **or** newline-delimited JSON file `data/raw/YYYY-MM-DD.jsonl`).
- Emit a `messages_received_total` counter (Prometheus format or simple log line).

### Windower (`processing/windower.py`)

- Consume from storage or subscribe to a second MQTT topic.
- Collect 30 consecutive telemetry samples per `location_id`.
- Build feature vector: `[accel_rms_mean, accel_rms_std, spl_mean, spl_std, spl_p90, spl_max]`.
- Feed to `model/inference.py` → receive score 0–100.
- Apply hysteresis:
  ```
  if score >= 65: state = "suitable"
  elif score < 55: state = "not_suitable"
  else: state = prev_state   # hold — no transition
  ```
- Publish state-change message if state differs from previous.

### LSTM model (`processing/model/`)

```python
# train.py: expects CSV with columns matching feature vector above + label column
# Hyperparameters to expose as CLI args:
#   --seq-len 30 --hidden 64 --layers 2 --epochs 50 --lr 0.001
# Saves model to model/lstm_weights.pt

# inference.py: loads weights, exposes:
def score(feature_vector: list[float]) -> float:  # returns 0–100
```

> **Note:** If labeled training data is not yet available, implement a deterministic rule-based
> scorer as a drop-in substitute so the rest of the pipeline remains testable end-to-end.

### Storage schema (SQLite fallback)

```sql
CREATE TABLE raw_telemetry (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id    TEXT    NOT NULL,
    location_id  TEXT    NOT NULL,
    ts_utc       TEXT    NOT NULL,   -- ISO 8601
    accel_rms    REAL    NOT NULL,
    spl_db       REAL    NOT NULL,
    seq          INTEGER NOT NULL
);

CREATE TABLE location_state (
    location_id  TEXT    PRIMARY KEY,
    state        TEXT    NOT NULL,
    score        REAL    NOT NULL,
    updated_at   TEXT    NOT NULL
);
```

### Visualization

- **Option A (preferred):** Streamlit app in `visualization/dashboard.py`.
  - Tab 1: Live view — gauge per location (color-coded), last 5 min time-series of SPL and accel.
  - Tab 2: Historical — date-picker, histogram of SPL distribution, occupancy heatmap by hour.
- **Option B:** Grafana. Export panel JSON to `visualization/grafana/dashboard.json` and include
  import instructions in README.

---

## 7. Configuration & Secrets Handling — Deliverable 5

### `.env.example` (commit this; never commit `.env`)

```dotenv
# MQTT Broker
MQTT_HOST=localhost
MQTT_PORT=8883
MQTT_USERNAME=
MQTT_PASSWORD=

# TLS certificates (paths only — do not paste cert content here)
MQTT_CA_CERT=config/certs/ca.crt
MQTT_CLIENT_CERT=config/certs/client.crt
MQTT_CLIENT_KEY=config/certs/client.key

# Storage
STORAGE_BACKEND=sqlite            # sqlite | influxdb | file
SQLITE_PATH=data/ssp.db
INFLUX_URL=http://localhost:8086
INFLUX_TOKEN=
INFLUX_ORG=
INFLUX_BUCKET=smart_space_pulse

# Model
MODEL_WEIGHTS_PATH=processing/model/lstm_weights.pt
SCORE_HIGH_THRESHOLD=65
SCORE_LOW_THRESHOLD=55

# Observability
LOG_LEVEL=INFO
METRICS_PORT=9090
```

### `.gitignore` must include

```
.env
*.key
*.pem
*.p12
config/certs/*.crt
config/certs/*.key
data/raw/
processing/model/lstm_weights.pt
__pycache__/
*.pyc
.DS_Store
```

### Certificate rotation (`config/certs/README_CERTS.md`)

Document steps to:
1. Generate a new client keypair (`openssl req ...`).
2. Sign with the broker CA.
3. Update `.env` paths on each device and server.
4. Restart affected services.
5. Revoke the old certificate.

### IAM policy sample (`config/iam_policy.json.example`)

Provide a redacted AWS IoT or GCP IAM policy allowing only:
- `iot:Publish` on `ssp/{location_id}/telemetry`
- `iot:Subscribe` on `ssp/#` (server only)
- No wildcard `*` resource ARNs.

---

## 8. Observability & Tests — Deliverable 6

### Metrics to track (log or expose via Prometheus)

| Metric | Type | Description |
|--------|------|-------------|
| `messages_received_total` | Counter | Total MQTT messages ingested |
| `schema_validation_errors_total` | Counter | Messages that failed schema check |
| `window_processing_latency_ms` | Histogram | Time from window close to score publish |
| `state_transitions_total` | Counter | Location state changes (by location_id) |
| `mqtt_reconnects_total` | Counter | Broker reconnection events |

### `observability/replay.py`

```bash
# Feed a recorded JSONL file through the full processing pipeline
python observability/replay.py \
  --file data_samples/mqtt_messages.jsonl \
  --speed 10 \        # 10x realtime
  --dry-run           # skip publish, print results to stdout
```

### `observability/sample_logs/`

Include two real or representative log files:
- `success.log`: end-to-end pipeline run with state transitions.
- `failure.log`: schema validation error + recovery.

Log format for all components:
```
2026-04-17T14:23:01.000Z [INFO ] [ingestor] Received telemetry from core2-a1b2 seq=4201
2026-04-17T14:23:30.000Z [INFO ] [windower] location=library-1f score=67.2 state=suitable
2026-04-17T14:25:01.000Z [ERROR] [ingestor] Schema error on core2-a1b2: missing field 'spl_db'
```

### Tests (`tests/`)

| File | What it tests |
|------|---------------|
| `test_feature_extractor.py` | RMS accel, SPL dB math with known inputs |
| `test_windower.py` | Hysteresis logic (all three zones), window boundary conditions |
| `test_inference.py` | Scorer returns float in [0, 100]; rule-based fallback |
| `test_mqtt_schema.py` | Valid/invalid payloads for all three message types |

Run: `pytest tests/ -v --tb=short`

---

## 9. Data Samples — Deliverable 7

### `data_samples/sensor_readings.csv`

```csv
ts_utc,device_id,location_id,accel_rms,spl_db,seq
2026-04-17T14:20:00.000Z,core2-a1b2,library-1f,0.21,58.3,1
2026-04-17T14:20:01.000Z,core2-a1b2,library-1f,0.19,57.1,2
...
```

Include at least 90 rows (3 complete windows) covering both "suitable" and "not suitable" ground truth.

### `data_samples/DATA_DICTIONARY.md`

| Field | Unit | Range | Notes |
|-------|------|-------|-------|
| `accel_rms` | m/s² | 0 – ~20 | RMS of 3-axis accel over 1-second window |
| `spl_db` | dB SPL | 30 – 100 | A-weighted equivalent level |
| `score` | dimensionless | 0 – 100 | LSTM output; higher = more suitable |
| `ts_utc` | ISO 8601 UTC | – | Device clock; NTP-synced if WiFi available |

---

## 10. Results Report — Deliverable 8

Generate or maintain `results/report.md` with these sections:

```markdown
## Methodology
- Describe data collection setup (locations, duration, # devices).
- Explain feature engineering and LSTM training procedure.
- Describe how ground truth labels were collected.

## KPIs

| KPI | Target | Achieved |
|-----|--------|----------|
| Occupancy classification accuracy | ≥ 85 % | TBD |
| False alarm rate (unsuitable flagged as suitable) | ≤ 10 % | TBD |
| End-to-end latency (sensor → dashboard) | ≤ 5 s | TBD |
| Message throughput | ≥ 1 msg/sec/device | TBD |

## Results
(Paste confusion matrix, latency histogram, sample dashboard screenshot.)

## Limitations
- Small labeled dataset; model may not generalize across venue types.
- Device clock drift if NTP unavailable.
- LSTM not yet running on-device; edge fallback is rule-based only.

## Next Steps
- Collect labeled data across ≥ 3 venue types.
- Experiment with Transformer encoder for better long-range sequence modeling.
- Deploy on-device quantized MLP as second-level gate.
```

---

## 11. Claude Code Behavioral Rules

1. **Never commit secrets.** If a task requires a credential, add it to `.env.example` and load
   it with `os.getenv(...)`. Raise `ValueError` at startup if a required env var is missing.

2. **Schema first.** Before writing any producer or consumer code, confirm the payload schema in
   `messaging/schema.md` matches the JSON structures in §5 of this file.

3. **Test before marking complete.** Every new function in `processing/` or `device/` must have a
   corresponding test in `tests/`. Run `pytest` before declaring a task done.

4. **Keep the feature vector stable.** The LSTM input shape is fixed at 6 features per window:
   `[accel_rms_mean, accel_rms_std, spl_mean, spl_std, spl_p90, spl_max]`. Any change must be
   coordinated across `windower.py`, `model/train.py`, and `model/inference.py` simultaneously.

5. **Log at the right level.** `DEBUG` for per-sample events, `INFO` for per-window events,
   `WARNING` for schema issues or reconnects, `ERROR` for unrecoverable failures. Never use
   `print()` in production code — use the `logging` module.

6. **Timestamps are always UTC.** Use `datetime.utcnow().isoformat() + "Z"` or
   `datetime.now(timezone.utc).isoformat()`. No local timezone offsets anywhere.

7. **Hysteresis is sacred.** Do not simplify the decision policy to a single threshold. The
   55/65 band is a core design requirement and must be preserved exactly.
