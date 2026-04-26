"""
Smart Space Pulse — LSTM Model Training

Trains a binary-classifier LSTM on 30-sample SPL windows to predict
suitability (suitable / not_suitable). Output is P(suitable) in [0, 1];
inference.py scales it to a 0-100 score.

Data source: JSONL windows written by processing/model/generate_synthetic.py
(both data_samples/recorded/ and data_samples/synthetic/).

Each input sample is a (30, 5) tensor: 30 timesteps of 5 features per step.
Per-timestep features are computed on a short rolling sub-window so the
LSTM sees temporal evolution rather than one static feature vector repeated.

Usage:
    python -m processing.model.train --epochs 40
"""
import argparse
import glob
import json
import logging
import os
import random
import sys

import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader, random_split

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

logger = logging.getLogger("train")

INPUT_FEATURES = 5  # spl_mean, spl_std, spl_p90, spl_max, spl_spike_count
SEQ_LEN = 30
ROLLING_SUB_WINDOW = 8  # per-timestep features computed from last N samples


def _per_timestep_features(spl: list[float], sub_window: int = ROLLING_SUB_WINDOW) -> list[list[float]]:
    """Compute one 5-feature vector per timestep using a rolling sub-window.

    For timestep t, the features are computed over spl[max(0, t-sub_window+1) : t+1].
    """
    features = []
    for t in range(len(spl)):
        lo = max(0, t - sub_window + 1)
        w = spl[lo:t + 1]
        n = len(w)
        mean = sum(w) / n
        std = (sum((x - mean) ** 2 for x in w) / n) ** 0.5
        sw = sorted(w)
        p90 = sw[min(int(0.9 * n), n - 1)]
        mx = max(w)
        if std < 1e-6:
            spikes = 0
        else:
            thresh = mean + 1.5 * std
            spikes = sum(1 for x in w if x > thresh)
        features.append([mean, std, p90, mx, float(spikes)])
    return features


def _label_from_path(path: str) -> int:
    """Derive binary label from filename convention.

    rec_suit_*  / syn_suit_*  -> 1 (suitable)
    rec_notsuit_* / syn_notsuit_* -> 0 (not_suitable)
    """
    name = os.path.basename(path)
    if "_suit_" in name:
        return 1
    if "_notsuit_" in name:
        return 0
    raise ValueError(f"Cannot infer label from filename: {name}")


class OccupancyDataset(Dataset):
    """Loads 30-sample SPL windows from JSONL and emits (seq, features) tensors."""

    def __init__(self, jsonl_paths: list[str]):
        self.paths = jsonl_paths
        self.samples = []
        self.labels = []
        for path in jsonl_paths:
            spl = []
            with open(path) as f:
                for line in f:
                    spl.append(float(json.loads(line)["spl_db"]))
            if len(spl) != SEQ_LEN:
                continue
            features = _per_timestep_features(spl)
            self.samples.append(features)
            self.labels.append(_label_from_path(path))
        logger.info("Loaded %d windows (suitable=%d, not_suitable=%d)",
                    len(self.samples),
                    sum(1 for y in self.labels if y == 1),
                    sum(1 for y in self.labels if y == 0))

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        x = torch.tensor(self.samples[idx], dtype=torch.float32)  # (30, 5)
        y = torch.tensor(self.labels[idx], dtype=torch.float32)
        return x, y


class OccupancyLSTM(nn.Module):
    """LSTM binary classifier: (batch, 30, 5) -> P(suitable) in [0, 1]."""

    def __init__(self, input_size: int = INPUT_FEATURES, hidden_size: int = 32,
                 num_layers: int = 1, dropout: float = 0.2):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.fc = nn.Sequential(
            nn.Linear(hidden_size, 16),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(16, 1),
            nn.Sigmoid(),
        )

    def forward(self, x):
        if x.dim() == 2:
            x = x.unsqueeze(0)
        lstm_out, _ = self.lstm(x)
        last_step = lstm_out[:, -1, :]
        return self.fc(last_step).squeeze(-1)


def collect_paths(roots: list[str]) -> list[str]:
    paths = []
    for r in roots:
        paths.extend(sorted(glob.glob(os.path.join(r, "*.jsonl"))))
    return paths


def train(args):
    random.seed(args.seed)
    torch.manual_seed(args.seed)

    paths = collect_paths(args.data_dirs)
    if not paths:
        raise RuntimeError(f"No JSONL windows found in {args.data_dirs}")
    random.shuffle(paths)

    dataset = OccupancyDataset(paths)
    n_val = max(1, int(len(dataset) * args.val_frac))
    n_train = len(dataset) - n_val
    train_ds, val_ds = random_split(dataset, [n_train, n_val],
                                    generator=torch.Generator().manual_seed(args.seed))

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False)

    model = OccupancyLSTM(hidden_size=args.hidden, num_layers=args.layers)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)
    criterion = nn.BCELoss()

    logger.info("Training LSTM: %d train / %d val, %d parameters",
                n_train, n_val, sum(p.numel() for p in model.parameters()))

    best_val = float("inf")
    for epoch in range(1, args.epochs + 1):
        model.train()
        train_loss = 0.0
        correct = 0
        total = 0
        for x, y in train_loader:
            optimizer.zero_grad()
            pred = model(x)
            loss = criterion(pred, y)
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * x.size(0)
            correct += ((pred >= 0.5).float() == y).sum().item()
            total += x.size(0)
        train_loss /= total
        train_acc = correct / total

        model.eval()
        val_loss = 0.0
        v_correct = 0
        v_total = 0
        with torch.no_grad():
            for x, y in val_loader:
                pred = model(x)
                loss = criterion(pred, y)
                val_loss += loss.item() * x.size(0)
                v_correct += ((pred >= 0.5).float() == y).sum().item()
                v_total += x.size(0)
        val_loss /= v_total
        val_acc = v_correct / v_total

        if val_loss < best_val:
            best_val = val_loss
            os.makedirs(os.path.dirname(args.output), exist_ok=True)
            torch.save(model.state_dict(), args.output)

        if epoch == 1 or epoch % 5 == 0 or epoch == args.epochs:
            logger.info("Epoch %2d/%d  train_loss=%.4f acc=%.3f  val_loss=%.4f acc=%.3f",
                        epoch, args.epochs, train_loss, train_acc, val_loss, val_acc)

    logger.info("Best val loss=%.4f — model saved to %s", best_val, args.output)


def parse_args():
    parser = argparse.ArgumentParser(description="Train binary LSTM occupancy classifier")
    parser.add_argument("--data-dirs", nargs="+",
                        default=["data_samples/recorded", "data_samples/synthetic"],
                        help="Directories containing JSONL windows")
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--hidden", type=int, default=32)
    parser.add_argument("--layers", type=int, default=1)
    parser.add_argument("--lr", type=float, default=0.002)
    parser.add_argument("--val-frac", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default="processing/model/lstm_weights.pt")
    return parser.parse_args()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.000Z [%(levelname)-5s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    args = parse_args()
    train(args)


if __name__ == "__main__":
    main()
