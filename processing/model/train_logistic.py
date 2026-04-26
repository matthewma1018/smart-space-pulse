"""
Smart Space Pulse — Logistic Regression Baseline

Trains a logistic regression classifier on the same 30-sample SPL windows
used for the LSTM, then prints a side-by-side comparison.

Feature vector per window (5 elements):
    [spl_mean, spl_std, spl_p90, spl_max, spl_spike_count]

Logistic regression receives one flat 5-element vector per window.
LSTM receives a (30, 5) per-timestep rolling sequence.
Both are evaluated on an identical held-out test split.

Usage:
    python -m processing.model.train_logistic
"""
import argparse
import glob
import json
import logging
import os
import random
import sys

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, classification_report,
                             confusion_matrix)
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

logger = logging.getLogger("train_logistic")

SEQ_LEN = 30
ROLLING_SUB_WINDOW = 8  # must match inference.py / train.py


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

def window_level_features(spl: list[float]) -> list[float]:
    """5-element window-level feature vector."""
    n = len(spl)
    mean = sum(spl) / n
    std = (sum((x - mean) ** 2 for x in spl) / n) ** 0.5
    sw = sorted(spl)
    p90 = sw[min(int(0.9 * n), n - 1)]
    mx = max(spl)
    thresh = mean + 1.5 * std if std > 1e-6 else float("inf")
    spikes = float(sum(1 for x in spl if x > thresh))
    return [mean, std, p90, mx, spikes]


def per_timestep_features(spl: list[float]) -> list[list[float]]:
    """Rolling sub-window features used by the LSTM."""
    features = []
    for t in range(len(spl)):
        lo = max(0, t - ROLLING_SUB_WINDOW + 1)
        w = spl[lo:t + 1]
        n = len(w)
        mean = sum(w) / n
        std = (sum((x - mean) ** 2 for x in w) / n) ** 0.5
        sw = sorted(w)
        p90 = sw[min(int(0.9 * n), n - 1)]
        mx = max(w)
        thresh = mean + 1.5 * std if std > 1e-6 else float("inf")
        spikes = float(sum(1 for x in w if x > thresh))
        features.append([mean, std, p90, mx, spikes])
    return features


def label_from_path(path: str) -> int:
    name = os.path.basename(path)
    if "_suit_" in name:
        return 1
    if "_notsuit_" in name:
        return 0
    raise ValueError(f"Cannot infer label from: {name}")


def load_dataset(data_dirs: list[str]):
    paths = []
    for d in data_dirs:
        paths.extend(sorted(glob.glob(os.path.join(d, "*.jsonl"))))

    X_flat, X_seq, y = [], [], []
    for path in paths:
        spl = []
        with open(path) as f:
            for line in f:
                spl.append(float(json.loads(line)["spl_db"]))
        if len(spl) != SEQ_LEN:
            continue
        X_flat.append(window_level_features(spl))
        X_seq.append(per_timestep_features(spl))
        y.append(label_from_path(path))

    return X_flat, X_seq, y


# ---------------------------------------------------------------------------
# LSTM evaluation helper
# ---------------------------------------------------------------------------

def eval_lstm(X_seq, y, weights_path: str):
    """Run the trained LSTM on a list of (30,5) sequences; return predictions."""
    try:
        import torch
        from processing.model.train import OccupancyLSTM
        model = OccupancyLSTM(input_size=5)
        model.load_state_dict(torch.load(weights_path, map_location="cpu", weights_only=True))
        model.eval()
        preds = []
        with torch.no_grad():
            for seq in X_seq:
                x = torch.tensor(seq, dtype=torch.float32).unsqueeze(0)  # (1,30,5)
                prob = float(model(x).item())
                preds.append(1 if prob >= 0.5 else 0)
        return preds
    except Exception as e:
        logger.error("LSTM eval failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def train(args):
    random.seed(args.seed)
    np.random.seed(args.seed)

    X_flat, X_seq, y = load_dataset(args.data_dirs)
    n = len(X_flat)
    logger.info("Loaded %d windows (suitable=%d, not_suitable=%d)",
                n, sum(y), n - sum(y))

    # Shuffle then split train / val / test
    indices = list(range(n))
    random.shuffle(indices)
    n_test = max(1, int(n * args.test_frac))
    n_val = max(1, int(n * args.val_frac))
    n_train = n - n_val - n_test

    train_idx = indices[:n_train]
    val_idx = indices[n_train:n_train + n_val]
    test_idx = indices[n_train + n_val:]

    def gather(idx, X):
        return [X[i] for i in idx]

    Xf_tr, Xf_va, Xf_te = (gather(train_idx, X_flat),
                             gather(val_idx, X_flat),
                             gather(test_idx, X_flat))
    Xs_te = gather(test_idx, X_seq)
    y_tr = [y[i] for i in train_idx]
    y_va = [y[i] for i in val_idx]
    y_te = [y[i] for i in test_idx]

    # Scale features (important for logistic regression)
    scaler = StandardScaler()
    Xf_tr_s = scaler.fit_transform(Xf_tr)
    Xf_va_s = scaler.transform(Xf_va)
    Xf_te_s = scaler.transform(Xf_te)

    # Train logistic regression
    lr = LogisticRegression(max_iter=1000, random_state=args.seed, C=1.0)
    lr.fit(Xf_tr_s, y_tr)

    lr_train_acc = accuracy_score(y_tr, lr.predict(Xf_tr_s))
    lr_val_acc = accuracy_score(y_va, lr.predict(Xf_va_s))
    lr_te_pred = lr.predict(Xf_te_s)
    lr_test_acc = accuracy_score(y_te, lr_te_pred)

    logger.info("Logistic  train=%.3f  val=%.3f  test=%.3f",
                lr_train_acc, lr_val_acc, lr_test_acc)

    # LSTM on same test split
    lstm_te_pred = eval_lstm(Xs_te, y_te, args.lstm_weights)

    # Save logistic model + scaler
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    joblib.dump({"model": lr, "scaler": scaler}, args.output)
    logger.info("Logistic model saved to %s", args.output)

    # ---- Comparison table ----
    print("\n" + "=" * 60)
    print("  Model Comparison — held-out test set "
          f"(n={len(y_te)}, suitable={sum(y_te)}, not={len(y_te)-sum(y_te)})")
    print("=" * 60)

    def report(name, preds):
        if preds is None:
            print(f"\n  {name}: evaluation failed")
            return
        acc = accuracy_score(y_te, preds)
        cm = confusion_matrix(y_te, preds)
        cr = classification_report(y_te, preds,
                                   target_names=["not_suitable", "suitable"],
                                   digits=3)
        print(f"\n  {name}  (test accuracy: {acc:.3f})")
        print(f"  Confusion matrix (rows=actual, cols=predicted):")
        print(f"                  not_suit  suit")
        print(f"    actual not:   {cm[0,0]:>6d}    {cm[0,1]:>4d}")
        print(f"    actual suit:  {cm[1,0]:>6d}    {cm[1,1]:>4d}")
        print()
        for line in cr.strip().split("\n"):
            print("  " + line)

    report("Logistic Regression (5 window features)", lr_te_pred)

    if lstm_te_pred is not None:
        report("LSTM  (30×5 per-timestep rolling features)", lstm_te_pred)

    # Feature coefficients
    feat_names = ["spl_mean", "spl_std", "spl_p90", "spl_max", "spl_spike_count"]
    print("\n  Logistic regression coefficients (positive = more suitable):")
    coefs = list(zip(feat_names, lr.coef_[0]))
    for fname, c in sorted(coefs, key=lambda x: -abs(x[1])):
        bar = ("+" if c > 0 else "") + f"{c:+.3f}"
        print(f"    {fname:20s}  {bar}")
    print("=" * 60 + "\n")


def parse_args():
    p = argparse.ArgumentParser(description="Train logistic regression baseline")
    p.add_argument("--data-dirs", nargs="+",
                   default=["data_samples/recorded", "data_samples/synthetic"])
    p.add_argument("--val-frac", type=float, default=0.15)
    p.add_argument("--test-frac", type=float, default=0.15)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--output", default="processing/model/logistic_model.joblib")
    p.add_argument("--lstm-weights", default="processing/model/lstm_weights.pt")
    return p.parse_args()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.000Z [%(levelname)-5s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    train(parse_args())


if __name__ == "__main__":
    main()
