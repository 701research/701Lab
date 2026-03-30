# Raspberry Pi Measurement Node Setup

This document summarizes the setup and configuration of the 701Lab Raspberry Pi measurement node.

The structure is based on the v4 integrated node setup, which includes GPS, temperature sensing, USB microphone, Polar H9, and IMU integration. In addition, an RTC module (DS3231) was later added to improve time stability immediately after boot, especially in offline operation.

---

## 1. Hardware Overview

**Main unit**
- Raspberry Pi 4 Model B (4GB RAM)
- Raspberry Pi OS (64-bit / Bookworm-based)
- Metal enclosure with cooling fan

**Connected devices**
- GPS: Waveshare L76K GPS HAT (UART)
- Temperature: DS18B20 waterproof temperature sensors ×2 (1-Wire)
- User interface: LED-equipped momentary switch
- Storage: USB memory (USB 3.0)
- Audio input: USB microphone
- Heart rate monitor: Polar H9 (BLE, HR / RR interval)
- IMU: WITMOTION BWT901CL (MPU9250, USB-Serial / CH340)
- RTC: DS3231 (I2C)

---

## 2. GPIO and Interface Assignment

| Purpose | GPIO | Pin | Notes |
|---|---:|---:|---|
| GPS UART TX | GPIO14 | Pin 8 | `ttyS0` |
| GPS UART RX | GPIO15 | Pin 10 | `ttyS0` |
| GPS STANDBY | GPIO4 | Pin 7 | HAT control |
| GPS SET | GPIO17 | Pin 11 | HAT control |
| Temperature sensor (1-Wire) | GPIO23 | Pin 16 | DS18B20 ×2 |
| Switch input | GPIO27 | Pin 13 | Short press / long press |
| Status LED (PWM) | GPIO13 | Pin 33 | PWM control |
| I2C SDA | GPIO2 | Pin 3 | DS3231 SDA |
| I2C SCL | GPIO3 | Pin 5 | DS3231 SCL |

**Note**
- If the DS3231 INT/SQW pin is used, avoid conflict with GPIO4, which is already assigned to GPS HAT standby control.
- For normal RTC operation, only VCC / GND / SDA / SCL are required.

---

## 3. OS Initial Setup and Python Environment

On Raspberry Pi OS Bookworm, a dedicated Python virtual environment is used for the measurement node.

```bash
sudo apt install -y python3-full python3-venv
python3 -m venv /home/seven_zero_one/venv701
source /home/seven_zero_one/venv701/bin/activate
pip install numpy pandas matplotlib scipy pyserial
```

Depending on the logger implementation, additional packages may also be needed for BLE, GPIO, or device-specific handling.

---

## 4. `config.txt` Settings

Configuration file:
- `/boot/firmware/config.txt`
- or `/boot/config.txt` depending on the system image

Design policy:
- Keep Bluetooth enabled for Polar H9 / H10 operation
- Use UART exclusively for GPS
- Use GPIO23 for 1-Wire temperature sensors
- Disable onboard audio to avoid conflict with PWM LED
- Enable I2C for DS3231 RTC

Example:

```ini
# avoid conflict with PWM LED
dtparam=audio=off

[all]
# enable UART for GPS
enable_uart=1

# 1-Wire temperature sensors (DS18B20) on GPIO23
dtoverlay=w1-gpio,gpiopin=23

# I2C for DS3231 RTC
dtparam=i2c_arm=on
dtoverlay=i2c-rtc,ds3231
```

---

## 5. Device Recognition and Verification

### 5.1 Temperature Sensors (DS18B20)
Recognition check:
```bash
ls /sys/bus/w1/devices/
```

Expected result:
- Two sensors detected
- CRC OK
- Temperature values readable

### 5.2 GPS (UART)
Device:
- `/dev/ttyS0`

Basic check:
```bash
sudo cat /dev/ttyS0
```

Expected result:
- NMEA sentences such as `GNGGA`, `GNRMC`, `GNZDA`
- Indoor operation may remain unfixed
- Outdoor operation should allow GPS fix

### 5.3 USB Microphone
Checks:
```bash
lsusb
arecord -l
arecord -L
```

Expected result:
- USB microphone recognized as a USB audio input device
- Available as an ALSA recording device

### 5.4 Polar H9 (BLE)
Example checks:
```bash
hciconfig
bluetoothctl info <device_mac>
```

Typical use:
- HR and RR interval logging via BLE
- In some environments, `gatttool`-based subprocess logging has been more stable than D-Bus-based notification handling

### 5.5 IMU (WITMOTION BWT901CL)
USB recognition:
```bash
lsusb
ls -l /dev/ttyUSB*
dmesg | tail -n 5
```

Expected result:
- CH340 serial converter recognized
- Assigned to `/dev/ttyUSB0` or similar

Raw data check:
```bash
python3 - <<'EOF'
import serial
ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=1)
print(ser.read(33).hex())
ser.close()
EOF
```

Expected result:
- Continuous 11-byte frames beginning with `0x55`
- Frame types include acceleration, angular velocity, angle, and magnetic field

### 5.6 RTC (DS3231)
I2C check:
```bash
ls /dev/i2c*
sudo i2cdetect -y 1
```

Expected result:
- Device visible at `0x68`

RTC device check:
```bash
dmesg | grep -i rtc
ls -l /dev/rtc*
```

Expected result:
- `/dev/rtc0` is created
- RTC driver is properly attached

---

## 6. RTC (DS3231) Notes

The DS3231 RTC is used to improve time stability immediately after boot, especially in offline operation.

Typical steps:

### 6.1 Enable I2C
```bash
sudo raspi-config
# Interface Options -> I2C -> Enable
sudo reboot
```

### 6.2 Install I2C tools
```bash
sudo apt update
sudo apt install -y i2c-tools
```

### 6.3 Verify RTC overlay and device creation
After adding the RTC overlay in `config.txt`, reboot and confirm:
```bash
sudo i2cdetect -y 1
dmesg | grep -i rtc
ls -l /dev/rtc*
```

### 6.4 Disable `fake-hwclock` if necessary
```bash
sudo systemctl disable --now fake-hwclock
sudo apt purge -y fake-hwclock
```

### 6.5 Synchronize system time and RTC
Write correct system time to RTC:
```bash
sudo hwclock -w
sudo hwclock -r
```

Or read RTC into system time:
```bash
sudo hwclock -s
date
```

**Operational note**
- The RTC is used as a boot-time support clock.
- Internal measurement synchronization should still rely on monotonic time.
- GPS remains the preferred final external reference when absolute time correction is needed.

---

## 7. USB Storage and Directory Structure

Typical USB mount point:
- `/media/seven_zero_one/MF-SU2C`

Run-based data structure:

```text
701lab_data/
└─ runs/
   └─ <run_id>/
      ├─ meta/
      ├─ raw/
      ├─ derived/
      ├─ qc/
      ├─ exports/
      ├─ calib/
      ├─ logs/
      └─ _inbox/
```

This structure is intended to separate raw logs, metadata, derived data, quality control outputs, exports, calibration assets, and operational logs.

---

## 8. Switch and LED UI Design

### LED Status Design

| State | LED behavior | Meaning |
|---|---|---|
| Power off | Off | No power |
| Booting | Fast blink (0.2 s) | Initializing |
| Idle | Off | Waiting to start |
| Waiting for GPS fix | Slow blink (1.0 s) | Synchronization in progress |
| Measuring | Solid on | Recording |
| Stopping | Medium blink (0.5 s) | Finalizing files |
| USB not detected | Two blinks, pause | Physical error |
| Temperature abnormal | Three blinks, pause | Sensor abnormality |
| Fatal error | Continuous fast blink | Immediate attention required |

### Switch Operation Design

| Action | State | Behavior |
|---|---|---|
| Short press | Idle | Start measurement |
| Short press | Measuring | Ignore |
| Long press (2 s) | Measuring | Stop measurement |
| Long press | Idle | No action |

---

## 9. State Machine Overview

Main states:

```text
BOOTING -> IDLE -> GPS_WAIT -> MEASURING -> STOPPING -> IDLE
```

Error conditions are treated as higher-priority overlays, and the system should return to `IDLE` after recovery whenever possible.

---

## 10. Current Scope

At this stage, the Raspberry Pi measurement node includes:

- Raspberry Pi 4 initial setup
- GPS and temperature sensor integration
- USB microphone recognition
- Polar H9 connection and HR / RR logging support
- IMU recognition and continuous logging
- Run-based directory structure for data output
- Switch / LED user interface design
- RTC (DS3231) addition for improved boot-time time stability

---

## 11. Design Notes

- The node is designed as a measurement platform, not as a general-purpose Raspberry Pi environment.
- Internal synchronization should be based primarily on monotonic time.
- Wall-clock time is useful for file naming, human-readable logs, and external alignment.
- RTC improves startup stability, while GPS can later serve as the more accurate time reference.

---

## 12. Future Additions

Planned or possible future extensions include:

- Additional USB devices
- Further audio validation and recording tests
- Bluetooth sensor expansion
- Improved power-noise handling
- More formalized time-correction logging and metadata export
