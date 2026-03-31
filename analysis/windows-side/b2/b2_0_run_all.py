#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable

def run(cmd):
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=HERE, check=True)

def main():
    print("[INFO] Phase B2 pipeline start")
    print(f"[INFO] python : {PY}")
    print(f"[INFO] scripts: {HERE}")

    # B2-1
    print("\n========== B2-1 ==========")
    run([PY, "b2_1_make_targets.py", "--work-root", r"D:\701lab\work", "--also-csv"])

    # B2-2a
    print("\n========== B2-2a ==========")
    run([PY, "b2_2a_extract_unified.py", "--work-root", r"D:\701lab\work", "--also-csv"])

    # B2-2b
    print("\n========== B2-2b ==========")
    run([PY, "b2_2b_raw_audio_imu_to_parquet.py", "--work-root", r"D:\701lab\work"])

    # B2-3
    print("\n========== B2-3 ==========")
    run([PY, "b2_3_compute_sensor_stats.py", "--work-root", r"D:\701lab\work", "--also-csv"])

    # B2-4
    print("\n========== B2-4 ==========")
    run([PY, "b2_4_make_figures.py", "--work-root", r"D:\701lab\work"])

    # B2-5
    print("\n========== B2-5 ==========")
    run([PY, "b2_5_sensor_quality.py", "--work-root", r"D:\701lab\work", "--also-csv"])

    # B2-6
    print("\n========== B2-6 ==========")
    run([PY, "b2_6_freeze_b2_summary.py", "--work-root", r"D:\701lab\work", "--also-csv"])

    print("\n[OK] Phase B2 pipeline completed successfully")

if __name__ == "__main__":
    main()
