#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B1_0: Run Phase B1 pipeline (B1-1 .. B1-5) in one shot.

Assumptions:
- This script is placed in the same directory as:
  b1_1_scan_runs.py
  b1_2_collect_qc.py
  b1_3_measure_data_volume.py
  b1_4_assign_flags.py
  b1_5_finalize_and_report.py

Run (PowerShell):
  conda activate phaseb
  python b1_0_run_all.py

Optional:
  python b1_0_run_all.py --also-csv
  python b1_0_run_all.py --min-span-s 120
  python b1_0_run_all.py --work-root D:/701lab/work --immutable-root D:/701lab/immutable
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple


def run_step(py: Path, args: List[str]) -> Tuple[int, str]:
    cmd = [sys.executable, str(py), *args]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = ""
    if p.stdout:
        out += p.stdout
    if p.stderr:
        out += ("\n" if out else "") + p.stderr
    return p.returncode, out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--immutable-root", default=r"D:\701lab\immutable", help="Immutable root that contains runs/")
    ap.add_argument("--work-root", default=r"D:\701lab\work", help="Work root that contains phaseB/")
    ap.add_argument("--also-csv", action="store_true", help="Write CSV alongside parquet where supported")
    ap.add_argument("--min-span-s", type=float, default=60.0, help="B1-4 minimum active span to accept run")
    ap.add_argument("--no-figures", action="store_true", help="B1-5: skip figures")
    args = ap.parse_args()

    here = Path(__file__).resolve().parent

    steps = [
        ("B1-1", here / "b1_1_scan_runs.py", [
            "--immutable-root", args.immutable_root,
            "--work-root", args.work_root,
        ] + (["--also-csv"] if args.also_csv else [])),

        ("B1-2", here / "b1_2_collect_qc.py", [
            "--work-root", args.work_root,
        ] + (["--also-csv"] if args.also_csv else [])),

        ("B1-3", here / "b1_3_measure_data_volume.py", [
            "--work-root", args.work_root,
        ] + (["--also-csv"] if args.also_csv else [])),

        ("B1-4", here / "b1_4_assign_flags.py", [
            "--work-root", args.work_root,
            "--min-span-s", str(args.min_span_s),
        ] + (["--also-csv"] if args.also_csv else [])),

        ("B1-5", here / "b1_5_finalize_and_report.py", [
            "--work-root", args.work_root,
        ] + (["--no-figures"] if args.no_figures else [])),
    ]

    print("[INFO] Phase B1 pipeline start")
    print(f"[INFO] python: {sys.executable}")
    print(f"[INFO] scripts: {here}")
    print(f"[INFO] immutable_root: {args.immutable_root}")
    print(f"[INFO] work_root: {args.work_root}")
    print(f"[INFO] also_csv: {args.also_csv}")
    print(f"[INFO] min_span_s: {args.min_span_s}")
    print(f"[INFO] no_figures: {args.no_figures}")
    print()

    for name, script, sargs in steps:
        if not script.exists():
            print(f"[NG] missing script: {script}")
            return 2

        print(f"========== {name} ==========")
        rc, out = run_step(script, sargs)
        if out.strip():
            print(out.rstrip())
        if rc != 0:
            print(f"[NG] {name} failed with exit code {rc}")
            return rc
        print(f"[OK] {name} done\n")

    print("[OK] Phase B1 pipeline completed successfully")
    print(f"[OK] Entry (B2/B3): {Path(args.work_root)/'phaseB'/'derived'/'b1'/'run_summary.parquet'}")
    print(f"[OK] Report:         {Path(args.work_root)/'phaseB'/'reports'/'b1_summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
