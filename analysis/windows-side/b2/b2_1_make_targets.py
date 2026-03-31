#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase B2-1: Create B2 targets table from B1 run_summary (entry for B2)

Input:
  work/phaseB/derived/b1/run_summary.parquet

Outputs:
  work/phaseB/derived/b2/_staging/b2_1_targets.parquet
  (optional) work/phaseB/derived/b2/_staging/b2_1_targets.csv

Run:
  conda activate phaseb
  python b2_1_make_targets.py --also-csv
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-root", default=r"D:\701lab\work")
    ap.add_argument("--include-maybe", action="store_true", help="Include use_flag=maybe in targets")
    ap.add_argument("--run-id", default="", help="If set, restrict to a single run_id")
    ap.add_argument("--also-csv", action="store_true", help="Also write CSV")
    args = ap.parse_args()

    work_root = Path(args.work_root)
    b1_summary = work_root / "phaseB" / "derived" / "b1" / "run_summary.parquet"
    out_dir = work_root / "phaseB" / "derived" / "b2" / "_staging"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not b1_summary.exists():
        raise SystemExit(f"[NG] missing input: {b1_summary}")

    df = pd.read_parquet(b1_summary).copy()

    # basic sanity
    if "run_id" not in df.columns:
        raise SystemExit("[NG] run_summary missing required column: run_id")

    # filter by use_flag
    allowed = {"yes"}
    if args.include_maybe:
        allowed.add("maybe")

    if "use_flag" in df.columns:
        df["use_flag"] = df["use_flag"].astype(str).str.lower()
        df_f = df[df["use_flag"].isin(allowed)].copy()
    else:
        # if use_flag absent, be conservative and include none
        df_f = df.iloc[0:0].copy()

    # optional: restrict to a single run_id
    if args.run_id:
        df_f = df_f[df_f["run_id"] == args.run_id].copy()

    # define target schema for B2 (stable + minimal)
    wanted = [
        "run_id",
        "run_path_immutable",
        "version",
        "open_t_wall_iso_utc",
        "close_t_wall_iso_utc",
        "duration_s",
        "active_span_s",
        "unified_rows",
        "qc_overall",
        "use_flag",
        "use_reason",
        "has_imu",
        "has_audio",
        "has_polar",
        "has_gps",
        "has_temp",
        "close_ok",
        "close_reason",
    ]
    wanted = [c for c in wanted if c in df_f.columns]
    out = df_f[wanted].copy()

    # add B2 bookkeeping
    out["b2_target_created_at_iso_utc"] = datetime.now(timezone.utc).isoformat()
    out["b2_target_reason"] = "use_flag_filter"
    if args.run_id:
        out["b2_target_reason"] = "use_flag_filter+run_id"

    # sort for reproducibility
    if "open_t_wall_iso_utc" in out.columns:
        out = out.sort_values(["open_t_wall_iso_utc", "run_id"], kind="mergesort")
    else:
        out = out.sort_values(["run_id"], kind="mergesort")

    out_parquet = out_dir / "b2_1_targets.parquet"
    out.to_parquet(out_parquet, index=False)

    if args.also_csv:
        out_csv = out_dir / "b2_1_targets.csv"
        out.to_csv(out_csv, index=False, encoding="utf-8-sig")

    # log summary
    print(f"[OK] read : {b1_summary}")
    print(f"[OK] wrote: {out_parquet}")
    if args.also_csv:
        print(f"[OK] wrote: {out_csv}")

    print(f"[INFO] targets: {len(out)}")
    if len(out) > 0:
        cols = ["run_id", "use_flag", "qc_overall", "active_span_s", "has_imu", "has_audio", "has_polar"]
        cols = [c for c in cols if c in out.columns]
        print("[INFO] preview:")
        print(out[cols].to_string(index=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
