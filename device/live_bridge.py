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

from dotenv import load_dotenv
load_dotenv()

import paho.mqtt.client as mqtt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from processing.storage import Storage
from processing.windower import Windower

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


# Streaming code: records one SPL reading, prints as JSON, repeats.
# Runs in an infinite loop on the device, outputting one JSON line per second.
STREAMING_CODE = """\
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
seq=0
while True:
    M5.update()
    t0=time.ticks_ms()
    spl=round(compute_spl(),2)
    t=time.localtime()
    ts='{}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}.000Z'.format(t[0],t[1],t[2],t[3],t[4],t[5])
    line=ujson.dumps({'device_id':'Core2Kit','location_id':'library-1f','ts_utc':ts,'spl_db':spl,'seq':seq})
    print(line)
    seq+=1
    el=time.ticks_diff(time.ticks_ms(),t0)
    if el<1000:
        time.sleep_ms(1000-el)
"""


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

    storage = Storage()
    storage._conn.execute("DELETE FROM raw_telemetry")
    storage._conn.execute("DELETE FROM location_state")
    storage._conn.commit()
    print("[INFO ] Cleared old data from database")
    windower = Windower()

    ser = serial.Serial(port, BAUD, timeout=5)
    time.sleep(0.5)

    # Send streaming code to device
    print("[INFO ] Starting streaming on device...")
    paste_exec(ser, STREAMING_CODE)
    time.sleep(3)  # wait for device to init and start outputting

    print("[INFO ] Live bridge running. Dashboard will update on refresh.")
    print("[INFO ] Make noise near the device to see state changes!")
    print("[INFO ] Press Ctrl-C to stop.\n")

    start_time = time.time()
    count = 0
    current_state = "not_suitable"

    try:
        while True:
            if args.duration > 0 and time.time() - start_time > args.duration:
                break

            # Read a line from device serial output
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

            # Validate basic fields
            if "spl_db" not in msg:
                continue

            # Write to SQLite
            storage.write_telemetry(msg)
            count += 1

            # Publish to AWS IoT Core
            if mqtt_client:
                location_id = msg.get("location_id", "library-1f")
                topic = f"ssp/{location_id}/telemetry"
                try:
                    mqtt_client.publish(topic, json.dumps(msg), qos=1)
                except Exception as e:
                    print(f"  [WARN ] MQTT publish failed: {e}")

            # Run through windower
            result = windower.ingest(msg)
            if result:
                storage.update_state(result["location_id"], result["state"], result["score"])
                current_state = result["state"]
                print(f"  >>> STATE: {result['prev_state']} -> {result['state']} "
                      f"(score={result['score']}) <<<")

            # Print every reading
            if count % 5 == 0 or result:
                print(f"  [{count}] SPL={msg['spl_db']:.1f} dB  state={current_state}")

    except KeyboardInterrupt:
        print(f"\n[INFO ] Stopped. {count} readings processed.")
    finally:
        storage.close()
        if mqtt_client:
            mqtt_client.disconnect()
        ser.close()


if __name__ == "__main__":
    main()
