# sensor-tests

This directory contains individual sensor bring-up and verification programs for the 701Lab acquisition layer.

The purpose of this area is to keep device-level checks separate from the integrated acquisition workflow.  
Scripts and notes placed here are intended for tasks such as:

- connection checks
- device recognition tests
- raw data readout
- communication verification
- small standalone logging tests

Current subdirectories:

- [temperature/](./temperature/)  
  Test scripts and notes for DS18B20 temperature sensors.

- [gps/](./gps/)  
  Test scripts and notes for GPS communication over UART.

- [usb-microphone/](./usb-microphone/)  
  Test scripts and notes for USB microphone recognition and basic audio input checks.

- [polar-h9/](./polar-h9/)  
  Test scripts and notes for Polar H9 BLE connection, heart rate, and RR interval acquisition.

- [imu-bwt901cl/](./imu-bwt901cl/)  
  Test scripts and notes for WITMOTION BWT901CL IMU recognition and raw data acquisition.

- [rtc-ds3231/](./rtc-ds3231/)  
  Test scripts and notes for DS3231 RTC recognition and basic timekeeping verification.

These materials are intended for sensor-level validation only.  
Integrated multi-sensor logging and state-based acquisition belong in [../integrated/](../integrated/).
