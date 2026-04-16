# Firmware Notes — M5Stack Core2

## UIFlow Version
- Developed with UIFlow v2.x (MicroPython firmware).
- Download from https://flow.m5stack.com

## Flashing via M5Burner
1. Download M5Burner for your OS from the M5Stack docs.
2. Connect Core2 via USB-C.
3. Select firmware: **UIFlow2 Core2 v2.x**.
4. Click **Burn** and wait for completion.

## Pin Assignments
| Function | Pin / Interface |
|----------|----------------|
| I2S Microphone (SPK) | I2S port A (CLK=12, DATA=0) |
| PDM Microphone (built-in) | GPIO 34 (internal I2S) |
| Accelerometer (IMU) | I2C (SDA=21, SCL=22, addr=0x68) |

## Serial Monitoring
```bash
# Linux / macOS
screen /dev/ttyUSB0 115200

# Windows (PowerShell)
# Use Device Manager to find COM port, then:
# Putty or Tera Term at COMx, 115200 baud
```
