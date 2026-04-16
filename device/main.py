"""
Smart Space Pulse — Device Entry Point
M5Stack Core2 / MicroPython

Usage:
    python device/main.py --sim       # local simulation mode
"""
import json
import time
import argparse


def main():
    parser = argparse.ArgumentParser(description="Smart Space Pulse Device")
    parser.add_argument("--sim", action="store_true", help="Run in local simulation mode")
    args = parser.parse_args()

    if args.sim:
        print("[SIM] Starting Smart Space Pulse device simulator...")
    else:
        print("[DEVICE] Initializing M5Stack Core2 sensors...")


if __name__ == "__main__":
    main()
