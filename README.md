# Smart Space Pulse

Real-time occupancy monitoring for shared spaces (libraries, lounges, cafés) using
M5Stack Core2 edge devices, AWS IoT Core, serverless Lambda inference, DynamoDB,
**and** a fully local backup pipeline. Two parallel ML scorers (LSTM + Logistic
Regression) are shown side-by-side on a Streamlit dashboard.

## Architecture

The same Core2 stream feeds two independent pipelines. Either side can fail
without taking the other down: `live_bridge.py` opens both MQTT clients in
parallel, and the dashboard probes DynamoDB at startup and falls back to SQLite
if the cloud is unreachable.

```
            Core2 (mic → SPL dB) → serial USB → live_bridge.py
                                              (publishes to BOTH)
       ┌──────────────────────────────────────────┴───────────────────────┐
       ▼ Cloud pipeline (logistic)                  ▼ Local pipeline (LSTM)
 AWS IoT Core (MQTT/TLS, mutual auth)        local Mosquitto (plain MQTT)
       │                                              │   localhost:1883
       ▼                                              ▼
   IoT Topic Rule                          processing/ingestor.py
       │                                              │
       ▼                                              ▼
 Lambda (ssp-inference)                     processing/windower.py
 ├── logistic regression (sklearn)          ├── LSTM (PyTorch, local)
 └── rule-based fallback                    └── hysteresis (55/65)
       │                                              │
       ▼                                              ▼
 DynamoDB (ssp-telemetry, ssp-state)        SQLite (data/ssp.db)
       │                                              │
       └────────────────► dashboard.py ◄──────────────┘
                       tries DynamoDB → SQLite on failure
                       LSTM column always rendered
                       Logistic column shows N/A in fallback
```

## Prerequisites

| Tool | Why |
|------|-----|
| Python 3.13 | runtime |
| [Mosquitto](https://mosquitto.org/download/) | local MQTT broker (Windows installer registers it as an auto-start service) |
| AWS account with IoT Core + DynamoDB + Lambda permissions | cloud pipeline (optional — local pipeline works without it) |
| M5Stack Core2 with mic | edge device |

```bash
pip install paho-mqtt plotly streamlit torch pytest python-dotenv pyserial scikit-learn joblib boto3
```

## Configure

```bash
cp .env.example .env
# edit MQTT_HOST, AWS_REGION, cert paths, etc.
```

For AWS IoT certs and IAM, see **[docs/CERTS.md](docs/CERTS.md)** — covers download,
install, rotation, and the AWS Academy session-token expiry gotcha.

## One-time cloud setup (skip if running local-only)

```bash
python -m cloud.setup_tables       # DynamoDB tables
python -m cloud.build_lambda       # bundle sklearn into a Lambda zip
python -m cloud.deploy_lambda      # upload + register Lambda
python -m cloud.setup_iot_rule     # wire IoT Topic Rule → Lambda
```

## Run

Mosquitto runs as a service on Windows after install (auto-starts with the OS).
Verify it's listening:

```bash
mosquitto_sub -h localhost -t 'ssp/#' -v        # should print incoming messages
```

**Terminal 1 — Live Bridge** (publishes to AWS *and* localhost in parallel):
```bash
python -u device/live_bridge.py
```

**Terminal 2 — Local Ingestor** (the LSTM pipeline; only needed if you want
the dashboard to keep working when AWS is down):
```bash
MQTT_HOST=localhost MQTT_PORT=1883 MQTT_USE_TLS=false python -u -m processing.ingestor
```

**Terminal 3 — Dashboard**:
```bash
python -u -m streamlit run visualization/dashboard.py --server.port 8501
```

Open http://localhost:8501 — auto-refreshes every 3 seconds. Make noise near
the device (clap, talk, music) and the cards update in real time.

The dashboard probes DynamoDB at startup. If reachable: cloud pipeline drives
state cards, both LSTM (local) and Logistic (cloud) scores show. If not: a
yellow "Cloud unreachable" banner appears, the dashboard reads from SQLite,
LSTM keeps rendering, Logistic shows N/A.

Run the cloud-only or local-only subset by skipping the irrelevant terminal —
the pipelines are independent.

## Feature vector

Each 30-sample window produces a 5-element vector:

| Feature | Description |
|---------|-------------|
| `spl_mean` | Mean SPL over the window |
| `spl_std` | Standard deviation |
| `spl_p90` | 90th percentile |
| `spl_max` | Maximum |
| `spl_spike_count` | Samples exceeding mean + 1.5σ (burstiness proxy) |

The LSTM receives a `(30 × 5)` sequence of rolling sub-window features. The
logistic regression receives a single 5-element window-level vector.

Hysteresis on the score: `≥65 → suitable`, `<55 → not_suitable`, otherwise
hold the previous state. This prevents flicker around the boundary.

## ML models

### LSTM (local)
- 1-layer LSTM, hidden size 32, sigmoid output → P(suitable)
- Input: `(30, 5)` per-timestep rolling features (sub-window size 8)
- BCELoss; 100% validation accuracy on synthetic dataset
- Weights: `processing/model/lstm_weights.pt`
- Runs in the dashboard process (PyTorch is too large for a Lambda zip)

### Logistic regression (cloud — Lambda)
- StandardScaler + sklearn LogisticRegression
- Input: 5-element window-level feature vector
- 100% test accuracy on the same split
- Bundled into `cloud/build/lambda.zip`
- Result written to `ssp-state` DynamoDB table

Both scores are shown side-by-side on every space card with an agreement badge.

## Training

```bash
python -m processing.model.generate_synthetic   # 600 labeled windows total
python -m processing.model.train --epochs 50 --lr 0.001
python -m processing.model.train_logistic       # prints comparison table
```

After retraining, rebuild + redeploy to update the cloud model:
```bash
python -m cloud.build_lambda && python -m cloud.deploy_lambda
```

## Other commands

```bash
pytest tests/ -v --tb=short                                          # 27 tests
python observability/replay.py --file <jsonl> --dry-run              # offline replay
```

## Troubleshooting

**Bridge says `[WARN ] Watchdog triggered — re-injecting streaming code`**
The Core2 went silent for >12 s. The bridge auto-recovers — usually fires once
on first start while the device boots, then stays clean.

**Bridge says `[WARN ] AWS IoT Core connect failed: ...`**
TLS or DNS issue. Run the local pipeline only — bridge keeps publishing to
localhost. Common cause: stale or wrong certificates. See docs/CERTS.md.

**Dashboard shows yellow `☁️ Cloud unreachable` banner**
DynamoDB probe failed. Most common cause: AWS Academy session token expired
(re-pull credentials). The LSTM half stays live from local SQLite; logistic
column shows N/A until AWS is back.

**Dashboard shows `Sensors are warming up`**
No state rows yet. Cloud path: check the Lambda logs in CloudWatch. Local path:
the windower needs 30 telemetry samples (~30 s) before it writes the first
state row.

**`No Core2 detected`**
The bridge looks for a CP210x USB-to-UART. Check Device Manager → Ports.
Override: `python device/live_bridge.py --port COM5`.

**Device unresponsive**
```python
import serial, time
ser = serial.Serial("COM5", 115200, timeout=3)
ser.write(b"\x03\x03"); time.sleep(0.5)
ser.write(b"import machine\r\nmachine.reset()\r\n")
time.sleep(2); ser.close()
```
The bridge watchdog re-injects the streaming code automatically afterward.

**`localhost:1883` connection refused**
Mosquitto not running. Windows: `net start mosquitto`. Linux:
`sudo systemctl start mosquitto`.

## Project structure

| Path | Purpose |
|------|---------|
| `device/live_bridge.py` | Serial reader → publishes to AWS + local MQTT in parallel; 12 s watchdog |
| `device/main_hw.py` | Core2 firmware (MicroPython, UIFlow2) |
| `device/feature_extractor.py` | SPL computation + windowing |
| `device/edge_policy.py` | On-device threshold rules |
| `device/display.py` | LCD/LED/buzzer helpers |
| `cloud/lambda_handler.py` | Lambda: validate → write → score → hysteresis → state |
| `cloud/dynamodb_storage.py` | boto3 DynamoDB storage |
| `cloud/build_lambda.py` / `deploy_lambda.py` | Lambda packaging + deploy |
| `cloud/setup_tables.py` / `setup_iot_rule.py` | One-time AWS resource setup |
| `processing/ingestor.py` | Local MQTT subscriber → SQLite + LSTM windower |
| `processing/windower.py` | 30-sample windows, LSTM scoring, hysteresis |
| `processing/storage.py` | SQLite backend; mirrors DynamoDB read interface for fallback |
| `processing/model/inference.py` | LSTM / logistic / rule-based scoring entry points |
| `processing/model/train{,_logistic}.py` | Training |
| `visualization/dashboard.py` | SpacePulse Streamlit UI; DynamoDB → SQLite fallback |
| `visualization/heatmap.py` | 5×5 simulated occupancy heatmap |
| `messaging/schema.md` | MQTT topic + payload contracts |
| `config/iam_policy_sample.json` | Redacted IAM policy reference |
| `docs/CERTS.md` | AWS IoT cert download / install / rotation |
| `data_samples/` | Recorded + synthetic labeled windows (see its README for units) |
| `observability/replay.py` | Replay JSONL through the pipeline |
| `tests/` | Pytest suite (27 tests) |
