# b2

This directory contains the Phase B2 Windows-side sensor-level extraction, statistics, visualization, and quality evaluation pipeline for the 701Lab project.

The purpose of B2 is to take the runs selected from B1, extract sensor-wise datasets, compute basic statistics, generate diagnostic figures, evaluate signal quality, and prepare a frozen summary table for B3.

At the current stage, the main components are:

- [b2_0_run_all.py](./b2_0_run_all.py)  
  Runs the full B2 pipeline in sequence.

- [b2_1_make_targets.py](./b2_1_make_targets.py)  
  Creates the B2 target table from the B1 run summary.

- [b2_2a_extract_unified.py](./b2_2a_extract_unified.py)  
  Extracts sensor-wise standardized parquet datasets from `unified.csv` for temperature, GPS, and Polar data.

- [b2_2b_raw_audio_imu_to_parquet.py](./b2_2b_raw_audio_imu_to_parquet.py)  
  Evaluates raw audio health and restores IMU raw binary data into frame-wise parquet datasets.

- [b2_3_compute_sensor_stats.py](./b2_3_compute_sensor_stats.py)  
  Computes basic sensor statistics for each run.

- [b2_4_make_figures.py](./b2_4_make_figures.py)  
  Generates basic per-run diagnostic figures.

- [b2_5_sensor_quality.py](./b2_5_sensor_quality.py)  
  Computes sensor quality metrics and derives run-level sensor usability flags.

- [b2_6_freeze_b2_summary.py](./b2_6_freeze_b2_summary.py)  
  Freezes the B2 summary table and prepares the entry point for B3.

The main output of this phase is a frozen sensor-informed summary table that supports the next stage of downstream analysis.
