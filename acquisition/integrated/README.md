# integrated

This directory contains the integrated acquisition programs used in the actual 701Lab measurement workflow.

Unlike the scripts in [../sensor-tests/](../sensor-tests/), the programs here are intended for multi-sensor operation under the run-based logging architecture of 701Lab.

Current contents:

- [int_log_temp_gps_polar_IMU_mic.py](./int_log_temp_gps_polar_IMU_mic.py)  
  The current integrated logger used in the Raspberry Pi measurement node.  
  It manages coordinated acquisition of temperature, GPS, Polar H9, IMU, and audio data, together with storage handling, run creation, switch / LED UI, and state-based operation.

This area is intended for practical measurement runs rather than standalone device checks.

As the repository structure evolves, integrated acquisition logic may later be refactored into smaller modules, but the current file reflects the actual working configuration used in 701Lab.
