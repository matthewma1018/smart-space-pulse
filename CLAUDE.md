# CLAUDE.md — Smart Space Pulse

> **For Claude Code:** This file is the canonical initialization guide for this project.
> Read it in full before touching any file. Do not commit secrets. Follow the directory layout exactly.

---

## 1. Project Overview

**Smart Space Pulse** monitors occupancy/noise in shared spaces (libraries, coworking, lounges)
using M5Stack Core2 edge devices, AWS IoT Core, and a real-time Streamlit dashboard.

### Architecture

```
Core2 (mic → SPL dB) → serial USB → live_bridge.py → AWS IoT Core (MQTT/TLS)
                                                           ↓
                                                   ingestor.py (subscriber)
                                                           ↓
                                               SQLite ← windower.py (30 samples)
                                                           ↓
                                               inference.py (score 0–100)
                                                           ↓
                                               hysteresis (≥65 suitable, <55 not)
                                                           ↓
                                                  dashboard.py (Streamlit)
```

### Key design decisions

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Edge | SPL audio (dB), no raw audio off-device | Privacy, bandwidth reduction |
| Transport | AWS IoT Core (MQTT over TLS 1.2, mutual auth) | Managed broker, IAM policies, cert auth |
| ML | LSTM (server-side, rule-based fallback active) | 30-step windows; iterate without reflashing |
| Decision | Hysteresis band 55/65 | Prevents state flickering |

---

## 2. Repository Layout

```
├── CLAUDE.md
├── README.md
├── .env.example
├── .gitignore
├── device/
│   ├── main_hw.py           ← Core2 firmware (MicroPython, publishes to AWS IoT Core)
│   ├── main.py              ← local simulator
│   ├── live_bridge.py       ← serial reader → AWS MQTT publisher (primary demo path)
│   ├── feature_extractor.py ← SPL computation
│   ├── edge_policy.py       ← on-device threshold rules
│   ├── display.py           ← LCD/LED/buzzer
│   ├── serial_logger.py     ← UART debug output
│   ├── serial_record.py     ← record samples to JSONL
│   ├── deploy_firmware.py   ← flash firmware to device
│   ├── secrets_example.py   ← template for WiFi/AWS credentials
│   └── FIRMWARE_NOTES.md    ← flash instructions
├── messaging/
│   ├── schema.md            ← MQTT topic hierarchy + field contracts
│   └── examples/            ← telemetry, state, alert JSON samples
├── processing/
│   ├── ingestor.py          ← MQTT subscriber → SQLite
│   ├── windower.py          ← 30-sample windows → 4-feature vector → hysteresis
│   ├── storage.py           ← SQLite (raw_telemetry + location_state tables)
│   └── model/
│       ├── train.py         ← LSTM training
│       ├── inference.py     ← score() function (rule-based fallback; LSTM when weights exist)
│       └── __init__.py
├── visualization/
│   └── dashboard.py         ← Streamlit (live gauges + historical charts)
├── config/
│   ├── .env.example
│   ├── iam_policy_sample.json
│   └── certs/               ← gitignored; place AmazonRootCA1.pem, certificate.pem.crt, private.pem.key
├── observability/
│   ├── replay.py            ← replay JSONL through pipeline
│   └── sample_logs/         ← success.log, failure.log
├── data_samples/
│   ├── sensor_readings.csv  ← ≥90 rows, SPL-only
│   ├── mqtt_messages.jsonl
│   └── real_sensor_log.jsonl
└── tests/
    ├── test_feature_extractor.py
    ├── test_windower.py
    ├── test_inference.py
    └── test_mqtt_schema.py
```

---

## 3. Pipeline Restart Guide

The Python executable path:
```
/c/Users/matth/AppData/Local/Microsoft/WindowsApps/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/python.exe
```

### Start order (3 background processes)

**Terminal 1 — Ingestor** (subscribes to AWS IoT Core):
```bash
python -m processing.ingestor
```

**Terminal 2 — Live Bridge** (reads Core2 serial, publishes to AWS, clears old DB):
```bash
python device/live_bridge.py
```

**Terminal 3 — Dashboard**:
```bash
streamlit run visualization/dashboard.py --server.port 8501
```

Dashboard auto-refreshes every 3 seconds at http://localhost:8501

### Single-command startup (Claude Code)

Start in this order as background tasks:
1. `python -m processing.ingestor`
2. `python device/live_bridge.py`
3. `python -m streamlit run visualization/dashboard.py --server.port 8501`

The live bridge automatically:
- Detects the Core2 on COM port (CP210x / Silicon Labs)
- Clears old data from SQLite (`DELETE FROM raw_telemetry`, `DELETE FROM location_state`)
- Injects SPL streaming code onto the device via serial paste-exec
- Publishes each reading to AWS IoT Core (`ssp/{location_id}/telemetry`)
- Writes to local SQLite + runs windower/scorer

### Important notes
- **Do NOT** delete `data/ssp.db` with `os.remove()` — it causes `PermissionError` when dashboard has it open. Use SQL `DELETE FROM` instead.
- **Client IDs**: device=`Core2Kit`, ingestor=`Core2Kit-ingestor`, bridge=`Core2Kit-bridge`. The AWS IAM policy must wildcard-match `Core2Kit*`.
- **Serial port**: device crashes if serial output buffer fills. The live bridge keeps the port open and drains it.
- **Device firmware**: `main_hw.py` runs on-device via UIFlow2. For demo purposes, `live_bridge.py` injects a smaller streaming snippet instead (more stable via paste-exec).

### Stop all

Kill all three background processes. If using Claude Code: stop all background shell tasks.

---

## 4. Schema Contracts

### MQTT topic hierarchy

```
ssp/{location_id}/telemetry    # 1 Hz sensor (QoS 1)
ssp/{location_id}/state        # state changes (QoS 1, retain=true)
ssp/{location_id}/alert        # threshold breaches (QoS 1)
ssp/{location_id}/heartbeat    # liveness (QoS 0)
```

### Telemetry payload

```json
{"device_id":"Core2Kit","location_id":"library-1f","ts_utc":"2026-04-17T14:23:01.000Z","spl_db":61.4,"seq":4201}
```

### State-change payload

```json
{"device_id":"Core2Kit","location_id":"library-1f","ts_utc":"...","score":67,"state":"suitable","prev_state":"not_suitable","window_sec":30}
```

### Schema validation rules (`tests/test_mqtt_schema.py`)
- `ts_utc`: ISO 8601 with `Z` suffix (UTC only)
- `device_id`: `Core2Kit` with optional alphanumeric suffix
- Numeric fields: `float`, never `null`
- `state`: one of `["suitable", "not_suitable", "transitioning"]`

---

## 5. Feature Vector & Scoring

Feature vector (4 elements, built per 30-sample window):
```
[spl_mean, spl_std, spl_p90, spl_max]
```

Must be coordinated across `windower.py`, `model/train.py`, `model/inference.py`.

### Rule-based scorer (active, no LSTM weights yet)

```python
# inference.py score()
# noise_penalty: 55-70 dB → 0-50, >70 dB → 50-80
# spike_penalty: >75 dB → up to 20
# score = 100 - noise_penalty - spike_penalty
```

### Hysteresis (windower.py)
```
score >= 65  → "suitable"
score <  55  → "not_suitable"
otherwise    → hold previous state
```

---

## 6. SQLite Schema

```sql
CREATE TABLE raw_telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL, location_id TEXT NOT NULL,
    ts_utc TEXT NOT NULL, spl_db REAL NOT NULL, seq INTEGER NOT NULL
);
CREATE TABLE location_state (
    location_id TEXT PRIMARY KEY, state TEXT NOT NULL,
    score REAL NOT NULL, updated_at TEXT NOT NULL
);
```

---

## 7. Configuration (.env)

See `.env.example`. Key variables:

| Variable | Purpose |
|----------|---------|
| `MQTT_HOST` | AWS IoT Core endpoint |
| `MQTT_PORT` | 8883 (TLS) or 1883 (local) |
| `MQTT_USE_TLS` | `true` for AWS |
| `MQTT_CA_CERT`, `MQTT_CLIENT_CERT`, `MQTT_CLIENT_KEY` | Paths in `config/certs/` |
| `SQLITE_PATH` | `data/ssp.db` |
| `SCORE_HIGH_THRESHOLD` / `SCORE_LOW_THRESHOLD` | 65 / 55 |

---

## 8. Deliverable Status

| Deliverable | Status | Notes |
|-------------|--------|-------|
| D1: Project scaffold | Done | Repo layout, .gitignore, CLAUDE.md |
| D2: Core2 firmware | Done | main_hw.py (AWS MQTT), live_bridge.py (serial), edge_policy, display |
| D3: MQTT schema | Done | messaging/schema.md + examples |
| D4: Cloud pipeline | Done | ingestor, windower, storage, dashboard (rule-based scorer) |
| D5: Config & secrets | Done | .env, IAM policy, cert rotation docs |
| D6: Observability | Done | replay.py, sample logs |
| D7: Data samples | Done | CSV (90+ rows), JSONL, real sensor log |

**Not yet done:**
- LSTM model training (rule-based scorer is the active fallback; train with `python processing/model/train.py` when labeled data available)

---

## 9. Behavioral Rules

1. **Never commit secrets.** Use `.env` + `python-dotenv`. Raise `ValueError` if required env var missing.
2. **Schema first.** Confirm payload schema in `messaging/schema.md` before writing producer/consumer code.
3. **Test before marking complete.** Run `pytest tests/ -v --tb=short`.
4. **Feature vector is 4 elements:** `[spl_mean, spl_std, spl_p90, spl_max]`. Changes must touch windower, train, inference simultaneously.
5. **Log levels:** DEBUG per-sample, INFO per-window, WARNING schema issues, ERROR unrecoverable. No `print()` in production.
6. **Timestamps always UTC.** `datetime.now(timezone.utc)`. No local offsets.
7. **Hysteresis is sacred.** 55/65 band must be preserved exactly.
