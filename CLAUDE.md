# CLAUDE.md — Smart Space Pulse: Tracking Human Activity with Sensors

> **For Claude Code:** This file is the canonical initialization guide for this project.
> Read it in full before touching any file. Every section maps to a required deliverable.
> Do not commit secrets. Do not skip the schema contracts. Follow the directory layout exactly.

---

## 1. Project Overview

**Smart Space Pulse** is an AIoT system that monitors occupancy and noise levels in shared spaces
(libraries, coworking offices, airport lounges, internet cafes) using M5Stack Core2 edge devices,
AWS IoT Core as the MQTT broker, a Python cloud processor, and a real-time dashboard.

### Architecture in one sentence

> Core2 devices stream 1 summary message/second over MQTT → a Python processor windows 30 samples
> → an LSTM classifier scores each location 0–100 → the dashboard shows occupancy state with
> hysteresis (≥ 65 = Suitable, < 55 = Not Suitable).

### Key design decisions

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Edge summarization | SPL audio (dB) | Privacy (no raw audio off-device), bandwidth reduction |
| Transport | AWS IoT Core (MQTT over TLS 1.2, mutual auth) | Managed broker; IAM policies per device; TLS cert-based auth |
| ML model | LSTM (server-side) | Sequential 30-step windows; easy iteration without reflashing firmware |
| Decision policy | Hysteresis band 55/65 | Prevents state flickering on borderline readings |

---

## 2. Repository Layout

```
smart-space-pulse/
├── CLAUDE.md                   ← you are here
├── README.md                   ← human quick-start
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
│   │   └── lstm_weights.pt     ← tracked via Git LFS or excluded; see §6
│   └── storage.py              ← write to SQLite
│
├── visualization/              ← Deliverable 4 (cont.)
│   └── dashboard.py            ← Streamlit app
│
├── config/                     ← Deliverable 5: configuration
│   ├── .env.example
│   ├── iam_policy_sample.json  ← redacted AWS IoT IAM policy (no real ARNs)
│   └── certs/                  ← placeholder; real certs gitignored
│       └── .gitkeep
│
├── observability/              ← Deliverable 6
│   ├── replay.py               ← feed recorded samples back through pipeline
│   └── sample_logs/
│       ├── success.log
│       └── failure.log
│
├── data_samples/               ← Deliverable 7
│   ├── sensor_readings.csv
│   └── mqtt_messages.jsonl
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

## 3. Device Code (Core2) — Deliverable 2

### Sensor pipeline

```
Raw microphone (PDM/analog)  →  RMS → 20·log10(·)  →  float dB SPL
```

Computed in a **1-second tumbling window** on-device before being packaged
into the outbound MQTT payload.

### Files to implement

**`device/feature_extractor.py`**
```python
# Must expose:
def compute_spl(samples: list[float]) -> float: ...         # returns dB SPL
def extract_window(audio_buf, window_sec=1) -> dict: ...
# Returns: {"spl_db": float, "ts_utc": str}
```

**`device/edge_policy.py`**
```python
# Lightweight on-device fallback rules (no network needed):
# If SPL > LOUD_THRESHOLD_DB: state = "busy"
# Configurable via constants at top of file; thresholds loaded from .env or hardcoded defaults.
LOUD_THRESHOLD_DB   = 75.0   # dB
```

**`device/display.py`**
- LCD: show current state ("Suitable" / "Not Suitable"), score, SPL.
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

## 4. Messaging & Schema — Deliverable 3

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
  "device_id":   "Core2Kit",
  "location_id": "library-1f",
  "ts_utc":      "2026-04-17T14:23:01.000Z",
  "spl_db":      61.4,
  "seq":         4201
}
```

### State-change payload

```json
{
  "device_id":   "Core2Kit",
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
  "device_id":   "Core2Kit",
  "location_id": "library-1f",
  "ts_utc":      "2026-04-17T14:25:00.000Z",
  "alert_type":  "noise_spike",
  "spl_db":      88.2,
  "threshold_db": 75.0
}
```

**Schema rules Claude Code must enforce in `tests/test_mqtt_schema.py`:**
- `ts_utc` must be ISO 8601 with `Z` suffix (UTC only — no local offsets).
- `device_id` format: `Core2Kit` with optional alphanumeric suffix (e.g. `Core2Kit-a1b2`).
- All numeric fields must be `float`, never `null`.
- `state` must be one of `["suitable", "not_suitable", "transitioning"]`.

---

## 5. Processing / Storage / Visualization — Deliverable 4

### Ingestor (`processing/ingestor.py`)

- Connect to AWS IoT Core endpoint using TLS mutual authentication (client cert + key + CA root).
- Subscribe to `ssp/#` with QoS 1.
- Validate schema (raise + log on failure, do not crash).
- Write raw messages to SQLite `raw_telemetry` table.
- For local development without AWS, fall back to a plain MQTT connection (`MQTT_USE_TLS=false`).

### Windower (`processing/windower.py`)

- Consume from storage or subscribe to a second MQTT topic.
- Collect 30 consecutive telemetry samples per `location_id`.
- Build feature vector: `[spl_mean, spl_std, spl_p90, spl_max]`.
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

Streamlit app in `visualization/dashboard.py`:
- Tab 1: Live view — gauge per location (color-coded), last 5 min time-series of SPL.
- Tab 2: Historical — date-picker, histogram of SPL distribution, occupancy heatmap by hour.

---

## 6. Configuration & Secrets Handling — Deliverable 5

### AWS IoT Core Setup

The system uses AWS IoT Core as its MQTT broker. Each Core2 device (and the cloud processor)
authenticates via X.509 certificates.

**Provisioning steps:**
1. In AWS IoT Core console, create a Thing (e.g. `Core2Kit`).
2. Generate or attach certificates: download the device certificate, private key, and AWS IoT root CA.
3. Attach an IAM policy granting publish/subscribe on `ssp/*` topics.
4. Place certificate files in `config/certs/` (gitignored) and point `.env` vars at them.

### IAM Policy Sample (`config/iam_policy_sample.json`)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "iot:Connect",
        "iot:Publish",
        "iot:Subscribe",
        "iot:Receive"
      ],
      "Resource": [
        "arn:aws:iot:us-east-1:123456789012:client/Core2Kit*",
        "arn:aws:iot:us-east-1:123456789012:topic/ssp/*"
      ]
    }
  ]
}
```

> **Note:** ARNs above are placeholders — replace with your actual account ID and region.

### Certificate Rotation

To replace a compromised or expired certificate:
1. Generate a new key pair and CSR (or use AWS IoT console to create one).
2. Register the new certificate on the Thing in AWS IoT Core.
3. Replace the files in `config/certs/` — no code changes needed.
4. Deactivate the old certificate in AWS IoT Core.
5. Restart the ingestor and/or device firmware.

### `.env.example` (commit this; never commit `.env`)

```dotenv
# AWS IoT Core
MQTT_HOST=XXXXXXXXXXXXX-ats.iot.us-east-1.amazonaws.com
MQTT_PORT=8883
MQTT_USE_TLS=true
MQTT_CA_CERT=config/certs/AmazonRootCA1.pem
MQTT_CLIENT_CERT=config/certs/device-cert.pem
MQTT_CLIENT_KEY=config/certs/device-key.pem
MQTT_THING_NAME=core2-a1b2

# Fallback: local broker for development without AWS
# MQTT_HOST=localhost
# MQTT_PORT=1883
# MQTT_USE_TLS=false

# Storage
SQLITE_PATH=data/ssp.db

# Model
MODEL_WEIGHTS_PATH=processing/model/lstm_weights.pt
SCORE_HIGH_THRESHOLD=65
SCORE_LOW_THRESHOLD=55

# Observability
LOG_LEVEL=INFO
```

### `.gitignore` must include

```
.env
*.key
*.pem
*.p12
config/certs/*.crt
data/raw/
processing/model/lstm_weights.pt
__pycache__/
*.pyc
.DS_Store
```


---

## 7. Observability & Tests — Deliverable 6

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
| `test_feature_extractor.py` | SPL dB math with known inputs |
| `test_windower.py` | Hysteresis logic (all three zones), window boundary conditions |
| `test_inference.py` | Scorer returns float in [0, 100]; rule-based fallback |
| `test_mqtt_schema.py` | Valid/invalid payloads for all three message types |

Run: `pytest tests/ -v --tb=short`

---

## 8. Data Samples — Deliverable 7

### `data_samples/sensor_readings.csv`

```csv
ts_utc,device_id,location_id,spl_db,seq
2026-04-17T14:20:00.000Z,Core2Kit,library-1f,58.3,1
2026-04-17T14:20:01.000Z,Core2Kit,library-1f,57.1,2
...
```

Include at least 90 rows (3 complete windows) covering both "suitable" and "not suitable" ground truth.

---

## 9. Claude Code Behavioral Rules

1. **Never commit secrets.** If a task requires a credential, add it to `.env.example` and load
   it with `os.getenv(...)`. Raise `ValueError` at startup if a required env var is missing.

2. **Schema first.** Before writing any producer or consumer code, confirm the payload schema in
   `messaging/schema.md` matches the JSON structures in §4 of this file.

3. **Test before marking complete.** Every new function in `processing/` or `device/` must have a
   corresponding test in `tests/`. Run `pytest` before declaring a task done.

4. **Keep the feature vector stable.** The LSTM input shape is fixed at 4 features per window:
   `[spl_mean, spl_std, spl_p90, spl_max]`. Any change must be
   coordinated across `windower.py`, `model/train.py`, and `model/inference.py` simultaneously.

5. **Log at the right level.** `DEBUG` for per-sample events, `INFO` for per-window events,
   `WARNING` for schema issues or reconnects, `ERROR` for unrecoverable failures. Never use
   `print()` in production code — use the `logging` module.

6. **Timestamps are always UTC.** Use `datetime.utcnow().isoformat() + "Z"` or
   `datetime.now(timezone.utc).isoformat()`. No local timezone offsets anywhere.

7. **Hysteresis is sacred.** Do not simplify the decision policy to a single threshold. The
   55/65 band is a core design requirement and must be preserved exactly.
