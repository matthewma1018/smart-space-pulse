"""
Smart Space Pulse — Serial Recorder

Controls the Core2 device over USB serial via paste mode (Ctrl+E).
Records real SPL data and pulls it back to the PC.

Usage:
    python device/serial_record.py                     # record 120 seconds
    python device/serial_record.py --duration 10       # record 10 seconds
    python device/serial_record.py --port COM5         # specify port
"""
import argparse
import os
import serial
import serial.tools.list_ports
import sys
import time

BAUD = 115200


def find_core2_port():
    for p in serial.tools.list_ports.comports():
        if "CP210x" in p.description or "Silicon Labs" in p.description:
            return p.device
    return None


def enter_repl(ser):
    ser.write(b"\x03")
    time.sleep(0.3)
    ser.write(b"\x03")
    time.sleep(0.3)
    _drain(ser)


def _drain(ser):
    while ser.in_waiting:
        ser.read(ser.in_waiting)
        time.sleep(0.02)


def read_all(ser, wait=0.5):
    time.sleep(wait)
    data = b""
    while ser.in_waiting:
        data += ser.read(ser.in_waiting)
        time.sleep(0.05)
    return data.decode("utf-8", errors="replace")


def paste_exec(ser, code):
    """Send code via MicroPython paste mode: Ctrl+E, paste, Ctrl+D."""
    enter_repl(ser)
    ser.write(b"\x05")  # Ctrl+E = paste mode
    time.sleep(0.3)
    _drain(ser)
    ser.write(code.encode())
    time.sleep(0.3)
    ser.write(b"\x04")  # Ctrl+D = execute


# Recording code (sent to device via paste mode)
RECORDING_CODE = """\
import M5
from M5 import *
import math,struct,time,ujson
M5.begin()
Mic.begin()
Mic.setSampleRate(8000)
buf=bytearray(16000)
def compute_spl():
    Mic.record(buf,8000,False)
    while Mic.isRecording():
        time.sleep_ms(10)
    samples=struct.unpack(chr(60)+'8000h',buf)
    rms=math.sqrt(sum(s*s for s in samples)/len(samples))
    if rms<1e-10:
        return 0.0
    return max(0.0,min(120.0,20.0*math.log10(rms/32768.0)+94.0))
try:
    os.remove('/flash/sensor_log.jsonl')
except:
    pass
for seq in range(__DURATION__):
    M5.update()
    t0=time.ticks_ms()
    spl=round(compute_spl(),2)
    t=time.localtime()
    ts='{}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}.000Z'.format(t[0],t[1],t[2],t[3],t[4],t[5])
    line=ujson.dumps({'device_id':'Core2Kit','location_id':'library-1f','ts_utc':ts,'spl_db':spl,'seq':seq})
    with open('/flash/sensor_log.jsonl','a') as f:
        f.write(line+chr(10))
    if seq%5==0:
        print('PROG',seq,spl)
    el=time.ticks_diff(time.ticks_ms(),t0)
    if el<1000:
        time.sleep_ms(1000-el)
f=open('/flash/sensor_log.jsonl','r')
lines=f.read().count(chr(10))
f.close()
print('DONE_COUNT',lines)
Mic.end()
"""

# Code to read file from device via paste mode
READ_FILE_CODE = """\
try:
    f=open('/flash/sensor_log.jsonl','r')
    data=f.read()
    f.close()
    print('FILE_START')
    print(data)
    print('FILE_END')
except Exception as e:
    print('FILE_ERROR:',e)
"""


def main():
    parser = argparse.ArgumentParser(description="Serial Recorder for Core2")
    parser.add_argument("--port", default=None, help="COM port (auto-detected)")
    parser.add_argument("--duration", type=int, default=120, help="Seconds to record")
    parser.add_argument("--output", default="data_samples/real_sensor_log.jsonl")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    port = args.port or find_core2_port()
    if not port:
        print("[ERROR] No Core2 detected. Connect device or use --port COMx")
        sys.exit(1)

    print(f"[INFO ] Core2 found on {port}")
    print(f"[INFO ] Recording {args.duration}s...")

    if args.dry_run:
        return

    ser = serial.Serial(port, BAUD, timeout=5)
    time.sleep(0.5)

    # Send recording code via paste mode
    code = RECORDING_CODE.replace("__DURATION__", str(args.duration))
    print("[INFO ] Sending recording script (paste mode)...")
    paste_exec(ser, code)

    # Wait for completion
    print(f"[INFO ] Recording in progress...")
    start_time = time.time()
    buf = ""
    done = False

    while time.time() - start_time < args.duration + 30:
        time.sleep(1)
        while ser.in_waiting:
            buf += ser.read(ser.in_waiting).decode("utf-8", errors="replace")

        # Check for progress and completion markers
        for line in buf.split("\n"):
            line = line.strip()
            if line.startswith("PROG"):
                parts = line.split()
                if len(parts) >= 3:
                    print(f"  [{int(parts[1])+1}/{args.duration}] SPL={parts[2]} dB")
            elif line.startswith("DONE_COUNT"):
                print("[INFO ] Recording complete!")
                done = True
            elif "Traceback" in line or "Error" in line:
                print(f"  [DEVICE] {line}")

        if done:
            break

    if not done:
        print("[WARN ] Timed out — recording may be incomplete")

    # Read file back using simple REPL commands (not paste mode)
    print("[INFO ] Pulling data from device...")
    time.sleep(1)
    enter_repl(ser)
    time.sleep(1)
    # Extra cleanup in case REPL is in weird state
    ser.write(b"\x03")
    time.sleep(0.5)
    _drain(ser)

    # Send commands one at a time with generous waits
    ser.write(b"import ujson\r\n")
    time.sleep(0.5)
    _drain(ser)

    ser.write(b"f=open('/flash/sensor_log.jsonl','r')\r\n")
    time.sleep(0.5)
    _drain(ser)

    ser.write(b"_d=f.read()\r\n")
    time.sleep(0.5)
    _drain(ser)

    ser.write(b"f.close()\r\n")
    time.sleep(0.5)
    _drain(ser)

    ser.write(b"print(_d)\r\n")
    time.sleep(3)

    resp = b""
    while ser.in_waiting:
        resp += ser.read(ser.in_waiting)
        time.sleep(0.1)
    time.sleep(1)
    while ser.in_waiting:
        resp += ser.read(ser.in_waiting)

    response = resp.decode("utf-8", errors="replace")
    ser.close()

    # Parse JSONL lines from the response
    contents = ""
    for line in response.split("\n"):
        line = line.strip()
        if line.startswith("{") and "device_id" in line:
            contents += line + "\n"

    if not contents:
        print("[ERROR] Could not read sensor_log.jsonl from device")
        print("[DEBUG] raw response:", repr(response[:500]))
        sys.exit(1)

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        f.write(contents)

    count = len(contents.strip().split("\n"))
    print(f"[INFO ] Saved {count} readings to {args.output}")

    # Preview
    lines = contents.strip().split("\n")
    print("[INFO ] Preview:")
    for line in lines[:3]:
        print(f"  {line}")


if __name__ == "__main__":
    main()
