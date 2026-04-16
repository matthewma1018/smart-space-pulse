# Smart Space Pulse — Results Report

## Methodology

- **Data collection setup:** M5Stack Core2 devices deployed in shared spaces (libraries, lounges).
- **Feature engineering:** 6-element feature vector computed per 30-sample window
  (accel_rms mean/std, SPL mean/std/p90/max).
- **Model:** LSTM with 2 layers, 64 hidden units, trained for 50 epochs.
- **Ground truth:** Manual occupancy labels collected during observation periods.
- **Evaluation:** Stratified split with 80/20 train/test ratio.

## KPIs

| KPI | Target | Achieved |
|-----|--------|----------|
| Occupancy classification accuracy | ≥ 85 % | TBD |
| False alarm rate (unsuitable flagged as suitable) | ≤ 10 % | TBD |
| End-to-end latency (sensor → dashboard) | ≤ 5 s | TBD |
| Message throughput | ≥ 1 msg/sec/device | TBD |

## Results

*(To be populated after model training and evaluation.)*

## Limitations

- Small labeled dataset; model may not generalize across venue types.
- Device clock drift if NTP unavailable.
- LSTM not yet running on-device; edge fallback is rule-based only.

## Next Steps

- Collect labeled data across ≥ 3 venue types.
- Experiment with Transformer encoder for better long-range sequence modeling.
- Deploy on-device quantized MLP as second-level gate.
