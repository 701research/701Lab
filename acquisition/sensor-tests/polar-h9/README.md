# polar-h9

This directory contains bring-up and verification scripts for the Polar H9 heart rate sensor used in the 701Lab measurement node.

Current contents:

- [polar_h9_bluepy_log.py](./polar_h9_bluepy_log.py)  
  Connects to Polar H9 over BLE using `bluepy`, enables Heart Rate Measurement notifications, and logs heart rate and RR interval data to CSV.

This script is intended for standalone device-level verification during setup and troubleshooting.  
It is not part of the integrated acquisition workflow.
