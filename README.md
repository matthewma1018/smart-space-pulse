# Smart Space Pulse

Real-time occupancy monitoring for shared spaces using M5Stack Core2 edge devices, AWS IoT Core, and an LSTM-based scoring pipeline.

## Quick Start

### 1. Install dependencies

```bash
pip install paho-mqtt plotly streamlit torch pytest python-dotenv pyserial
```

### 2. Configure AWS IoT Core

Copy `.env.example` to `.env` and fill in your AWS IoT Core endpoint and certificate paths:

```bash
cp .env.example .env
# Edit .env with your MQTT_HOST, cert paths, etc.
```

Place your certificates in `config/certs/`:
- `AmazonRootCA1.pem`
- `certificate.pem.crt`
- `private.pem.key`

### 3. Run the pipeline

Open **3 terminals** and run each command:

**Terminal 1 — Ingestor** (subscribes to AWS IoT Core):
```bash
python -m processing.ingestor
```

**Terminal 2 — Live Bridge** (reads Core2 mic over USB, publishes to AWS):
```bash
python device/live_bridge.py
```

**Terminal 3 — Dashboard**:
```bash
streamlit run visualization/dashboard.py --server.port 8501
```

Then open http://localhost:8501 in your browser. The dashboard auto-refreshes every 3 seconds.

The live bridge automatically detects the Core2 on the USB serial port and clears old data from the database.

### 4. Make some noise

Clap, talk, or play music near the Core2 device. You'll see the SPL reading, score, and occupancy state change in real time on the dashboard.

## Architecture

```
Core2 device (mic → SPL dB, 1 Hz)
    → USB serial
        → live_bridge.py
            → AWS IoT Core (MQTT over TLS 1.2)
                → ingestor.py (schema validation, SQLite storage)
                    → windower.py (30-sample windows, 4 features)
                        → rule-based scorer (0–100)
                            → hysteresis (≥65 suitable, <55 not suitable)
                                → Dashboard (Streamlit)
```

## Other Commands

### Simulate without hardware
```bash
python device/main.py --sim --profile transition --duration 60
```
Profiles: `quiet`, `busy`, `transition`.

### Replay recorded data
```bash
python observability/replay.py --file data_samples/mqtt_messages.jsonl --dry-run
```

### Train the LSTM model
```bash
python processing/model/train.py --epochs 50 --lr 0.001
```
Weights save to `processing/model/lstm_weights.pt`. Without weights, the rule-based scorer runs automatically.

### Run tests
```bash
pytest tests/ -v --tb=short
```

## Project Structure

| Directory | Purpose |
|-----------|---------|
| `device/` | Core2 firmware, live bridge, local simulator |
| `messaging/` | MQTT topic schema and payload examples |
| `processing/` | Ingestor, windower, LSTM model, SQLite storage |
| `visualization/` | Streamlit dashboard |
| `config/` | AWS IoT certs, IAM policy, env template |
| `observability/` | Replay tool and sample logs |
| `data_samples/` | Sample CSV and JSONL datasets |
| `tests/` | Pytest suite |
