"""
Smart Space Pulse — Core2 Firmware (MicroPython for UIFlow2)

Publishes telemetry to AWS IoT Core over MQTT with TLS mutual auth.
Includes microphone SPL recording, on-device display,
and edge policy classification.

Deploy: Flash via UIFlow2 or copy to device with mpremote.
"""
import M5
from M5 import *
import math
import struct
import time
import network
import ujson
from umqtt import MQTTClient

try:
    from secrets import WIFI_SSID, WIFI_PASSWORD, AWS_ENDPOINT
except ImportError:
    print("[WARN] secrets.py not found — copy secrets_example.py to secrets.py and fill in values")
    WIFI_SSID = "YOUR_WIFI_SSID"
    WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"
    AWS_ENDPOINT = "YOUR_AWS_IOT_ENDPOINT.amazonaws.com"

# ── Configuration ─────────────────────────────────────────────────────────────
DEVICE_ID   = "Core2Kit"
LOCATION_ID = "library-1f"

AWS_PORT  = 8883
CLIENT_ID = DEVICE_ID

# Cert paths on Core2 flash
CERT_FILE = "/flash/certificate/certificate.pem.crt"
KEY_FILE  = "/flash/certificate/private.pem.key"
CA_FILE   = "/flash/certificate/AmazonRootCA1.pem"

# Sensor
SAMPLE_RATE = 8000
RECORD_SECS = 1
REF_DB      = 94.0

# Edge policy thresholds
LOUD_THRESHOLD_DB = 75.0

# MQTT topics
TOPIC_TELEMETRY = "ssp/{}/telemetry".format(LOCATION_ID)
TOPIC_HEARTBEAT = "ssp/{}/heartbeat".format(LOCATION_ID)

PUBLISH_INTERVAL_MS   = 1000
HEARTBEAT_INTERVAL_MS = 30000

# ── Globals ───────────────────────────────────────────────────────────────────
mqtt_client = None
last_pub    = 0
last_hb     = 0
boot_ticks  = 0
seq         = 0

lbl_title = None
lbl_state = None
lbl_spl   = None

# ── WiFi ──────────────────────────────────────────────────────────────────────
def wait_wifi(timeout_s=20):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    t0 = time.time()
    while not wlan.isconnected():
        if time.time() - t0 > timeout_s:
            raise RuntimeError("WiFi connect timeout")
        time.sleep(0.2)
    print("[WiFi] Connected:", wlan.ifconfig()[0])
    # Sync RTC via NTP
    import ntptime
    try:
        ntptime.settime()
        print("[NTP] Time synced")
    except Exception as e:
        print("[NTP] Sync failed:", e)

# ── MQTT (AWS IoT Core TLS) ──────────────────────────────────────────────────
def mqtt_connect():
    key_b  = open(KEY_FILE, "rb").read()
    cert_b = open(CERT_FILE, "rb").read()
    ca_b   = open(CA_FILE, "rb").read()

    ssl_params = {
        "server_hostname": AWS_ENDPOINT,
        "key": key_b,
        "cert": cert_b,
        "cadata": ca_b,
    }

    c = MQTTClient(CLIENT_ID, AWS_ENDPOINT, port=AWS_PORT, keepalive=120,
                   ssl=True, ssl_params=ssl_params)
    c.connect(clean_session=True)
    print("[MQTT] Connected to", AWS_ENDPOINT)
    return c

# ── SPL Computation ──────────────────────────────────────────────────────────
def compute_spl(buf):
    samples = struct.unpack("<{}h".format(SAMPLE_RATE * RECORD_SECS), buf)
    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
    if rms < 1e-10:
        return 0.0
    return max(0.0, min(120.0, 20.0 * math.log10(rms / 32768.0) + REF_DB))

# ── Edge Policy ──────────────────────────────────────────────────────────────
def edge_classify(spl_db):
    if spl_db > LOUD_THRESHOLD_DB:
        return "busy"
    return "quiet"

# ── WiFi Diagnostics ─────────────────────────────────────────────────────────
def read_rssi():
    """Return WiFi RSSI in dBm, or 0 if unavailable."""
    try:
        wlan = network.WLAN(network.STA_IF)
        if not wlan.isconnected():
            return 0
        return int(wlan.status('rssi'))
    except Exception:
        return 0

# ── Display Helpers ──────────────────────────────────────────────────────────
def color_for_state(state):
    if state == "busy":
        return 0xe74c3c  # red
    return 0x2ecc71      # green

# ── Setup ────────────────────────────────────────────────────────────────────
def setup():
    global lbl_title, lbl_state, lbl_spl

    M5.begin()
    Widgets.fillScreen(0x222222)

    Mic.begin()
    Mic.setSampleRate(SAMPLE_RATE)

    lbl_title = Widgets.Label("Smart Space Pulse", 10, 8, 1.0,
                              0xffffff, 0x222222, Widgets.FONTS.DejaVu18)
    lbl_state = Widgets.Label("State: --", 10, 50, 1.0,
                              0x2ecc71, 0x222222, Widgets.FONTS.DejaVu18)
    lbl_spl   = Widgets.Label("SPL: -- dB", 10, 80, 1.0,
                              0xffffff, 0x222222, Widgets.FONTS.DejaVu18)

# ── Main Loop ────────────────────────────────────────────────────────────────
def loop():
    global mqtt_client, last_pub, last_hb, boot_ticks, seq

    if boot_ticks == 0:
        boot_ticks = time.ticks_ms()

    M5.update()

    # Record 1 second of audio and compute SPL
    buf = bytearray(SAMPLE_RATE * RECORD_SECS * 2)
    Mic.record(buf, SAMPLE_RATE, False)
    while Mic.isRecording():
        time.sleep_ms(10)

    spl_db    = round(compute_spl(buf), 2)
    state     = edge_classify(spl_db)

    # Update display
    lbl_state.setText("State: {}".format(state))
    lbl_spl.setText("SPL: {:.1f} dB".format(spl_db))

    # Publish telemetry every second
    now = time.ticks_ms()
    if time.ticks_diff(now, last_pub) >= PUBLISH_INTERVAL_MS:
        t = time.localtime()
        ts_utc = "{}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}.000Z".format(t[0], t[1], t[2], t[3], t[4], t[5])

        payload = ujson.dumps({
            "device_id":   DEVICE_ID,
            "location_id": LOCATION_ID,
            "ts_utc":      ts_utc,
            "spl_db":      spl_db,
            "seq":         seq,
        })

        try:
            if mqtt_client is None:
                mqtt_client = mqtt_connect()
            mqtt_client.publish(TOPIC_TELEMETRY, payload.encode())
            print("[{}] {} | {}".format(ts_utc, TOPIC_TELEMETRY, payload))
        except Exception as e:
            print("[ERROR] MQTT publish failed:", e)
            mqtt_client = None

        last_pub = now
        seq += 1

    # Publish heartbeat every 30 s (QoS 0, fire-and-forget)
    if time.ticks_diff(now, last_hb) >= HEARTBEAT_INTERVAL_MS:
        t = time.localtime()
        ts_utc = "{}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}.000Z".format(t[0], t[1], t[2], t[3], t[4], t[5])
        uptime_sec = time.ticks_diff(now, boot_ticks) // 1000
        hb_payload = ujson.dumps({
            "device_id":   DEVICE_ID,
            "location_id": LOCATION_ID,
            "ts_utc":      ts_utc,
            "uptime_sec":  uptime_sec,
            "rssi_dbm":    read_rssi(),
        })
        try:
            if mqtt_client is None:
                mqtt_client = mqtt_connect()
            mqtt_client.publish(TOPIC_HEARTBEAT, hb_payload.encode())
            print("[{}] {} | {}".format(ts_utc, TOPIC_HEARTBEAT, hb_payload))
        except Exception as e:
            print("[ERROR] heartbeat publish failed:", e)
            mqtt_client = None
        last_hb = now

# ── Entry Point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        setup()
        wait_wifi()
        mqtt_client = mqtt_connect()
        while True:
            loop()
    except (KeyboardInterrupt, Exception) as e:
        try:
            print("[STOPPED]", e)
        except Exception:
            pass
        finally:
            if mqtt_client:
                try:
                    mqtt_client.disconnect()
                except Exception:
                    pass
            Mic.end()
