"""
Smart Space Pulse — Serial Recording Script

Records real SPL + accel data from the Core2's mic and IMU,
saves to /flash/sensor_log.jsonl on the device.

Deploy and run:
    mpremote cp device/record_samples.py :record_samples.py
    mpremote run :record_samples.py

Then pull the data back:
    mpremote cp :sensor_log.jsonl data_samples/real_sensor_log.jsonl

Or paste into UIFlow2 web editor and run from there.
"""
import M5
from M5 import *
import math
import struct
import time
import ujson

# ── Config ────────────────────────────────────────────────────────────────────
SAMPLE_RATE = 8000
RECORD_SECS = 1
REF_DB      = 94.0
TOTAL_SECS  = 120       # how long to record (seconds)
OUTPUT_FILE = "/flash/sensor_log.jsonl"

# ── Init ──────────────────────────────────────────────────────────────────────
M5.begin()
Mic.begin()
Mic.setSampleRate(SAMPLE_RATE)

buf = bytearray(SAMPLE_RATE * RECORD_SECS * 2)

lbl = Widgets.Label("Recording... 0s", 10, 60, 1.0, 0xffffff, 0x222222,
                     Widgets.FONTS.DejaVu18)

# ── SPL ───────────────────────────────────────────────────────────────────────
def compute_spl():
    Mic.record(buf, SAMPLE_RATE, False)
    while Mic.isRecording():
        time.sleep_ms(10)
    samples = struct.unpack("<{}h".format(SAMPLE_RATE * RECORD_SECS), buf)
    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
    if rms < 1e-10:
        return 0.0
    return max(0.0, min(120.0, 20.0 * math.log10(rms / 32768.0) + REF_DB))

# ── Accel RMS ─────────────────────────────────────────────────────────────────
def compute_accel_rms(n=30):
    total = 0.0
    for _ in range(n):
        ax, ay, az = Imu.getAccel()
        mag = math.sqrt(ax * ax + ay * ay + az * az)
        total += mag * mag
        time.sleep_ms(2)
    return round(math.sqrt(total / n), 3)

# ── Record ────────────────────────────────────────────────────────────────────
print("[RECORD] Starting {} second capture...".format(TOTAL_SECS))

# Clear previous log
try:
    os.remove(OUTPUT_FILE)
except Exception:
    pass

seq = 0
for i in range(TOTAL_SECS):
    M5.update()
    t_start = time.ticks_ms()

    spl_db    = round(compute_spl(), 2)
    accel_rms = compute_accel_rms()
    ts_utc    = "{}Z".format(time.strftime("%Y-%m-%dT%H:%M:%S.000", time.gmtime()))

    line = ujson.dumps({
        "device_id":   "Core2Kit",
        "location_id": "library-1f",
        "ts_utc":      ts_utc,
        "accel_rms":   accel_rms,
        "spl_db":      spl_db,
        "seq":         seq,
    })

    with open(OUTPUT_FILE, "a") as f:
        f.write(line + "\n")

    print("[{}] spl={:.1f} dB  accel={:.3f} m/s2".format(seq, spl_db, accel_rms))
    lbl.setText("Rec: {}s | SPL {:.0f}dB".format(i + 1, spl_db))

    seq += 1

    # Maintain ~1 second cadence
    elapsed = time.ticks_diff(time.ticks_ms(), t_start)
    if elapsed < 1000:
        time.sleep_ms(1000 - elapsed)

lbl.setText("Done! {} samples saved.".format(seq))
print("[RECORD] Done. {} samples written to {}".format(seq, OUTPUT_FILE))

Mic.end()
