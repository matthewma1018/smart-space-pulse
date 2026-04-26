# Smart Space Pulse

Real-time occupancy monitoring for shared spaces using M5Stack Core2 edge devices, AWS IoT Core, and a dual-model ML scoring pipeline (LSTM + Logistic Regression).

## Quick Start

### 1. Install dependencies

```bash
pip install paho-mqtt plotly streamlit torch pytest python-dotenv pyserial scikit-learn joblib
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
python -u -m processing.ingestor
```

**Terminal 2 — Live Bridge** (reads Core2 mic over USB, publishes to AWS):
```bash
python -u device/live_bridge.py
```

**Terminal 3 — Dashboard**:
```bash
python -u -m streamlit run visualization/dashboard.py --server.port 8501
```

Then open http://localhost:8501 in your browser. The dashboard auto-refreshes every 3 seconds.

The live bridge automatically detects the Core2 on the USB serial port, resets old data, injects the MicroPython streaming code, and restarts it automatically if the device goes silent.

### 4. Make some noise

Clap, talk, or play music near the Core2 device. The dashboard will show the noise level change and update space status in real time.

## Architecture

```
Core2 device (mic → SPL dB, 1 Hz)
    → USB serial
        → live_bridge.py  [watchdog: auto re-injects code if device goes silent]
            → AWS IoT Core (MQTT over TLS 1.2)
                → ingestor.py (schema validation, SQLite storage)
                    → windower.py (30-sample windows → 5-feature vector)
                        → inference.py
                            ├── LSTM (primary)       → score 0–100
                            └── Rule-based fallback  → score 0–100
                        → hysteresis (≥65 suitable, <55 not suitable)
                            → Dashboard (Streamlit, SpacePulse UI)
                                └── Model comparison: LSTM vs Logistic
```

## Feature Vector

Each 30-sample window produces a 5-element feature vector:

| Feature | Description |
|---------|-------------|
| `spl_mean` | Mean SPL over the window |
| `spl_std` | Standard deviation |
| `spl_p90` | 90th percentile |
| `spl_max` | Maximum |
| `spl_spike_count` | Samples exceeding mean + 1.5σ (burstiness proxy) |

The LSTM receives a `(30 × 5)` sequence of rolling sub-window features. The logistic regression receives a single 5-element window-level summary vector.

## ML Models

### LSTM (primary)
- 1-layer LSTM, hidden size 32, sigmoid output → P(suitable)
- Input: `(30, 5)` per-timestep rolling features (sub-window size 8)
- Trained with BCELoss; achieves 100% validation accuracy on synthetic dataset
- Weights: `processing/model/lstm_weights.pt`

### Logistic Regression (baseline / comparison)
- StandardScaler + sklearn LogisticRegression
- Input: 5-element window-level feature vector
- Trained on the same dataset split; also achieves 100% test accuracy
- Model: `processing/model/logistic_model.joblib`

Both model scores are displayed side-by-side on the dashboard with an agreement indicator.

## Training

### Generate synthetic training data
```bash
python -m processing.model.generate_synthetic
```
Outputs `data_samples/recorded/` (60 windows: 50 suitable + 10 not-suitable) and
`data_samples/synthetic/` (540 amplified windows). Total: 600 labeled windows.

### Train the LSTM
```bash
python -m processing.model.train --epochs 50 --lr 0.001
```
Weights save to `processing/model/lstm_weights.pt`.

### Train the Logistic Regression baseline
```bash
python -m processing.model.train_logistic
```
Prints a side-by-side comparison table of both models on the held-out test set.

## Other Commands

### Run tests
```bash
pytest tests/ -v --tb=short
```

### Replay recorded data
```bash
python observability/replay.py --file data_samples/mqtt_messages.jsonl --dry-run
```

## Project Structure

| Path | Purpose |
|------|---------|
| `device/live_bridge.py` | Serial reader → AWS MQTT publisher, with 12 s watchdog |
| `device/main_hw.py` | Core2 firmware (MicroPython, UIFlow2) |
| `processing/ingestor.py` | MQTT subscriber → SQLite |
| `processing/windower.py` | 30-sample windows, 5-feature vector, hysteresis |
| `processing/model/inference.py` | LSTM + logistic + rule-based scoring entry points |
| `processing/model/train.py` | LSTM training |
| `processing/model/train_logistic.py` | Logistic regression training + model comparison |
| `processing/model/generate_synthetic.py` | Synthetic dataset generator |
| `visualization/dashboard.py` | SpacePulse customer dashboard (Streamlit) |
| `messaging/` | MQTT topic schema and payload examples |
| `config/` | AWS IoT certs, IAM policy, env template |
| `observability/` | Replay tool and sample logs |
| `data_samples/` | Recorded and synthetic labeled windows |
| `tests/` | Pytest suite |
