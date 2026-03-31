# temperature

This directory contains bring-up and verification scripts for DS18B20 temperature sensors used in the 701Lab measurement node.

Current contents:

- [temp_sensor_check.py](./temp_sensor_check.py)  
  Detects DS18B20 sensors under the Linux w1 interface and reads temperature values from each detected device.

This script is intended for sensor-level confirmation during setup and troubleshooting.  
It is not part of the integrated acquisition workflow.
