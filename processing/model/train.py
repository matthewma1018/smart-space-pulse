"""
Smart Space Pulse — LSTM Model Training

Usage:
    python processing/model/train.py --seq-len 30 --hidden 64 --layers 2 --epochs 50 --lr 0.001
"""
import argparse
import os


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
    print(f"[TRAIN] seq_len={args.seq_len}, hidden={args.hidden}, "
          f"layers={args.layers}, epochs={args.epochs}, lr={args.lr}")
    print(f"[TRAIN] Data: {args.data}")
    print(f"[TRAIN] Output: {args.output}")
    print("[TRAIN] TODO: implement LSTM training with PyTorch")


if __name__ == "__main__":
    main()
