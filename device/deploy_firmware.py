"""
Deploy main_hw.py to the Core2 device as /flash/main.py (runs on boot).
Requires secrets.py already on the device (see serial_record.py or UIFlow2).

Usage:
    python device/deploy_firmware.py
    python device/deploy_firmware.py --port COM5
"""
import json
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
    time.sleep(0.5)
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


def main():
    port = find_core2_port()
    if not port:
        print("[ERROR] No Core2 detected")
        sys.exit(1)

    print(f"[INFO ] Core2 on {port}")

    with open("device/main_hw.py", "r", encoding="utf-8") as f:
        firmware = f.read()
    print(f"[INFO ] Firmware: {len(firmware)} bytes")

    ser = serial.Serial(port, BAUD, timeout=5)
    time.sleep(0.5)

    # Write firmware to device using JSON encoding (handles all escaping)
    encoded = json.dumps(firmware)
    write_code = (
        f"_c={encoded}\n"
        "f=open('/flash/main.py','w')\n"
        "f.write(_c)\n"
        "f.close()\n"
        "print('WROTE',len(_c),'bytes')\n"
    )

    print("[INFO ] Deploying via paste mode...")
    paste_exec(ser, write_code)
    time.sleep(5)

    resp = b""
    while ser.in_waiting:
        resp += ser.read(ser.in_waiting)
        time.sleep(0.05)
    output = resp.decode("utf-8", errors="replace")
    print(output.strip())

    if "WROTE" in output:
        print("[INFO ] Firmware deployed successfully!")
        print("[INFO ] The device will run it on next boot.")
        print("[INFO ] Press the reset button on the Core2 to start.")
    else:
        print("[ERROR] Deployment failed")
        sys.exit(1)

    # Verify file exists
    enter_repl(ser)
    time.sleep(0.3)
    ser.write(b"import os\nprint(os.stat('/flash/main.py'))\r\n")
    time.sleep(1)
    resp2 = ser.read(ser.in_waiting) if ser.in_waiting else b""
    print("[VERIFY]", resp2.decode("utf-8", errors="replace").strip())

    ser.close()


if __name__ == "__main__":
    main()
