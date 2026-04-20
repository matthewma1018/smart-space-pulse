"""
Smart Space Pulse — LSTM Model Training

Trains a 2-layer LSTM on windowed sensor features to predict occupancy score (0–100).

Usage:
    python processing/model/train.py --seq-len 30 --hidden 64 --layers 2 --epochs 50 --lr 0.001
"""
import argparse
import csv
import logging
import os
import sys

import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

logger = logging.getLogger("train")

INPUT_FEATURES = 4  # spl_mean, spl_std, spl_p90, spl_max


class OccupancyDataset(Dataset):
    """Dataset of sliding windows over sensor features with rule-based labels."""

    def __init__(self, csv_path: str, seq_len: int = 30):
        self.seq_len = seq_len
        self.samples, self.labels = self._load_csv(csv_path)

    def _load_csv(self, path: str):
        rows = []
        with open(path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append({
                    "spl_db": float(row["spl_db"]),
                })

        if len(rows) < self.seq_len:
            raise ValueError(f"CSV has {len(rows)} rows, need at least {self.seq_len}")

        # Build sliding windows and compute features + label for each window
        samples = []
        labels = []
        for i in range(len(rows) - self.seq_len + 1):
            window = rows[i:i + self.seq_len]
            features = self._extract_features(window)
            label = self._compute_label(window)
            samples.append(features)
            labels.append(label)

        return samples, labels

    @staticmethod
    def _extract_features(window: list[dict]) -> list[float]:
        spl = [s["spl_db"] for s in window]
        n = len(window)
        spl_mean = sum(spl) / n
        spl_std = (sum((x - spl_mean) ** 2 for x in spl) / n) ** 0.5
        sorted_spl = sorted(spl)
        spl_p90 = sorted_spl[int(0.9 * n)]
        spl_max = max(spl)
        return [spl_mean, spl_std, spl_p90, spl_max]

    @staticmethod
    def _compute_label(window: list[dict]) -> float:
        """Generate a label using the same rule-based logic as inference.py."""
        spl_mean = sum(s["spl_db"] for s in window) / len(window)
        sorted_spl = sorted(s["spl_db"] for s in window)
        spl_p90 = sorted_spl[int(0.9 * len(window))]

        noise_penalty = min(spl_mean / 100.0, 1.0) * 50
        spike_penalty = max(0, (spl_p90 - 70) / 30.0) * 20
        score = 100.0 - noise_penalty - spike_penalty
        return max(0.0, min(100.0, score))

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        x = torch.tensor(self.samples[idx], dtype=torch.float32)
        y = torch.tensor(self.labels[idx], dtype=torch.float32)
        return x, y


class OccupancyLSTM(nn.Module):
    """LSTM regression model: 4 features → occupancy score 0–100."""

    def __init__(self, input_size: int = INPUT_FEATURES, hidden_size: int = 64,
                 num_layers: int = 2, dropout: float = 0.2):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.fc = nn.Sequential(
            nn.Linear(hidden_size, 32),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(32, 1),
        )

    def forward(self, x):
        # x shape: (batch, seq_len, input_size) — but our dataset returns (seq_len, input_size)
        if x.dim() == 2:
            x = x.unsqueeze(0)  # add batch dim
        lstm_out, _ = self.lstm(x)
        last_step = lstm_out[:, -1, :]  # (batch, hidden_size)
        return self.fc(last_step).squeeze(-1)


def train(args):
    dataset = OccupancyDataset(args.data, seq_len=args.seq_len)
    dataloader = DataLoader(dataset, batch_size=16, shuffle=True)

    model = OccupancyLSTM(
        input_size=INPUT_FEATURES,
        hidden_size=args.hidden,
        num_layers=args.layers,
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)
    criterion = nn.MSELoss()

    logger.info("Training LSTM: %d samples, %d parameters",
                len(dataset), sum(p.numel() for p in model.parameters()))

    for epoch in range(1, args.epochs + 1):
        model.train()
        epoch_loss = 0.0
        for batch_x, batch_y in dataloader:
            # batch_x: (batch, 4) — each row is a single window's feature vector
            # Reshape to (batch, seq_len=1, input_size=4) for LSTM
            batch_x = batch_x.unsqueeze(1)

            optimizer.zero_grad()
            output = model(batch_x)
            loss = criterion(output, batch_y)
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()

        avg_loss = epoch_loss / len(dataloader)
        if epoch % 10 == 0 or epoch == 1:
            logger.info("Epoch %d/%d  loss=%.4f", epoch, args.epochs, avg_loss)

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    torch.save(model.state_dict(), args.output)
    logger.info("Model saved to %s", args.output)


def parse_args():
    parser = argparse.ArgumentParser(description="Train LSTM occupancy classifier")
    parser.add_argument("--seq-len", type=int, default=30, help="Sequence length (window size)")
    parser.add_argument("--hidden", type=int, default=64, help="LSTM hidden units")
    parser.add_argument("--layers", type=int, default=2, help="Number of LSTM layers")
    parser.add_argument("--epochs", type=int, default=50, help="Training epochs")
    parser.add_argument("--lr", type=float, default=0.001, help="Learning rate")
    parser.add_argument("--data", type=str, default="data_samples/sensor_readings.csv",
                        help="Path to training CSV")
    parser.add_argument("--output", type=str, default="processing/model/lstm_weights.pt",
                        help="Output model path")
    return parser.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.000Z [%(levelname)-5s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    logger.info("Config: seq_len=%d, hidden=%d, layers=%d, epochs=%d, lr=%.4f",
                args.seq_len, args.hidden, args.layers, args.epochs, args.lr)
    logger.info("Data: %s", args.data)
    logger.info("Output: %s", args.output)
    train(args)


if __name__ == "__main__":
    main()
