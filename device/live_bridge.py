"""
Smart Space Pulse — Live Bridge

Records SPL from the Core2 via serial, publishes to AWS IoT Core via MQTT,
AND feeds the local pipeline in real-time.

Usage:
    python device/live_bridge.py                      # runs until Ctrl-C
    python device/live_bridge.py --duration 120       # stop after 120 seconds

Then open in another terminal:
    streamlit run visualization/dashboard.py
"""
import argparse
import json
import os
import ssl
import serial
import serial.tools.list_ports
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

import paho.mqtt.client as mqtt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


BAUD = 115200


def connect_aws_mqtt():
    """Connect to AWS IoT Core and return MQTT client."""
    host = os.getenv("MQTT_HOST")
    port = int(os.getenv("MQTT_PORT", "8883"))
    ca_path = os.getenv("MQTT_CA_CERT")
    cert_path = os.getenv("MQTT_CLIENT_CERT")
    key_path = os.getenv("MQTT_CLIENT_KEY")

    if not all([host, ca_path, cert_path, key_path]):
        print("[WARN ] AWS MQTT not configured, skipping cloud publish")
        return None

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_verify_locations(ca_path)
    ctx.load_cert_chain(cert_path, key_path)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="Core2Kit-bridge")
    client.tls_set_context(ctx)
    client.tls_insecure_set(False)
    client.connect(host, port, keepalive=60)
    client.loop_start()
    print(f"[INFO ] Connected to AWS IoT Core at {host}:{port}")
    return client


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


def paste_exec(ser, code):
    enter_repl(ser)
    ser.write(b"\x05")
    time.sleep(0.3)
    _drain(ser)
    ser.write(code.encode())
    time.sleep(0.3)
    ser.write(b"\x04")


# Streaming code injected into the Core2 via paste-exec.
# Measures SPL, updates the LCD display, and prints one JSON line per second.
STREAMING_CODE = """\
import M5
from M5 import *
import math,struct,time,ujson
M5.begin()
Widgets.fillScreen(0x222222)
Widgets.Label("Smart Space Pulse",10,8,1.0,0xffffff,0x222222,Widgets.FONTS.DejaVu18)
lbl_spl=Widgets.Label("SPL: -- dB",10,55,1.0,0x2ecc71,0x222222,Widgets.FONTS.DejaVu18)
lbl_lvl=Widgets.Label("Initializing...",10,90,1.0,0xaaaaaa,0x222222,Widgets.FONTS.DejaVu18)
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
seq=0
while True:
    M5.update()
    t0=time.ticks_ms()
    spl=round(compute_spl(),2)
    t=time.localtime()
    ts='{}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}.000Z'.format(t[0],t[1],t[2],t[3],t[4],t[5])
    line=ujson.dumps({'device_id':'Core2Kit','location_id':'library-1f','ts_utc':ts,'spl_db':spl,'seq':seq})
    print(line)
    lbl_spl.setText('SPL: {:.1f} dB'.format(spl))
    if spl<55:
        lbl_lvl.setColor(0x2ecc71,0x222222)
        lbl_lvl.setText('Quiet')
    elif spl<70:
        lbl_lvl.setColor(0xf39c12,0x222222)
        lbl_lvl.setText('Moderate')
    else:
        lbl_lvl.setColor(0xe74c3c,0x222222)
        lbl_lvl.setText('Loud')
    seq+=1
    el=time.ticks_diff(time.ticks_ms(),t0)
    if el<1000:
        time.sleep_ms(1000-el)
"""


WATCHDOG_TIMEOUT = 12   # seconds without a valid reading before re-injecting
REINJECT_COOLDOWN = 5   # seconds to wait after re-injection before reading again


def _inject_and_wait(ser):
    print("[WARN ] Watchdog triggered — re-injecting streaming code onto device")
    paste_exec(ser, STREAMING_CODE)
    time.sleep(REINJECT_COOLDOWN)


def main():
    parser = argparse.ArgumentParser(description="Live Bridge: Core2 -> SQLite pipeline")
    parser.add_argument("--port", default=None, help="COM port (auto-detected)")
    parser.add_argument("--duration", type=int, default=0, help="Seconds to run (0=until Ctrl-C)")
    args = parser.parse_args()

    port = args.port or find_core2_port()
    if not port:
        print("[ERROR] No Core2 detected")
        sys.exit(1)

    print(f"[INFO ] Core2 on {port}")

    mqtt_client = connect_aws_mqtt()

    ser = serial.Serial(port, BAUD, timeout=2)  # shorter timeout so watchdog fires promptly
    time.sleep(0.5)

    print("[INFO ] Starting streaming on device...")
    paste_exec(ser, STREAMING_CODE)
    time.sleep(3)

    print("[INFO ] Live bridge running. Dashboard will update on refresh.")
    print("[INFO ] Make noise near the device to see state changes!")
    print("[INFO ] Press Ctrl-C to stop.\n")

    start_time = time.time()
    last_reading = time.time()
    count = 0

    try:
        while True:
            if args.duration > 0 and time.time() - start_time > args.duration:
                break

            # Watchdog: re-inject if device goes silent
            if time.time() - last_reading > WATCHDOG_TIMEOUT:
                _inject_and_wait(ser)
                last_reading = time.time()
                continue

            raw = ser.readline()
            if not raw:
                continue

            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("{"):
                continue

            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            if "spl_db" not in msg:
                continue

            last_reading = time.time()

            # Overwrite device timestamp with host UTC (Core2 RTC is unsynchronized)
            msg["ts_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

            count += 1

            if mqtt_client:
                location_id = msg.get("location_id", "library-1f")
                topic = f"ssp/{location_id}/telemetry"
                try:
                    mqtt_client.publish(topic, json.dumps(msg), qos=1)
                except Exception as e:
                    print(f"  [WARN ] MQTT publish failed: {e}")

            if count % 5 == 0:
                print(f"  [{count}] SPL={msg['spl_db']:.1f} dB")

    except KeyboardInterrupt:
        print(f"\n[INFO ] Stopped. {count} readings processed.")
    finally:
        if mqtt_client:
            mqtt_client.disconnect()
        ser.close()


if __name__ == "__main__":
    main()
