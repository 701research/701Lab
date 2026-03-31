# b1

This directory contains the Phase B1 Windows-side cross-run preparation pipeline for the 701Lab project.

The purpose of B1 is to organize and screen multiple runs at a lightweight level before deeper sensor-level processing begins.

At the current stage, the main components are:

- [b1_0_run_all.py](./b1_0_run_all.py)  
  Runs the full B1 pipeline in sequence.

- [b1_1_scan_runs.py](./b1_1_scan_runs.py)  
  Scans immutable run directories and collects minimal metadata without reading large files.

- [b1_2_collect_qc.py](./b1_2_collect_qc.py)  
  Collects run-level QC summaries from `qc_report.json` or `qc_report.md`.

- [b1_3_measure_data_volume.py](./b1_3_measure_data_volume.py)  
  Measures lightweight data volume indicators such as unified row counts and active span.

- [b1_4_assign_flags.py](./b1_4_assign_flags.py)  
  Assigns comparison flags and preliminary `use_flag` decisions for each run.

- [b1_5_finalize_and_report.py](./b1_5_finalize_and_report.py)  
  Freezes the cross-run summary table and generates a concise report and distribution-level figures.

The main output of this phase is a stable run-level summary table that serves as the entry point for Phase B2 and later Windows-side processing.
