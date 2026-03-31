#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase B1-4: Assign comparison flags + use_flag (auto) and export editable run_flags.csv

Input:
  work/phaseB/derived/b1/_staging/b1_3_runs_with_volume.parquet

Outputs:
  work/phaseB/derived/b1/run_flags.csv
  work/phaseB/derived/b1/_staging/b1_4_runs_flagged.parquet
  (+ optional CSV for the parquet)

Run:
  conda activate phaseb
  python b1_4_assign_flags.py --also-csv
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd


def pick_active_span(row: pd.Series) -> Optional[float]:
    """Prefer segments_run span; fall back to duration_s."""
    v = row.get("active_span_s_segments_run")
    try:
        if pd.notna(v):
            return float(v)
    except Exception:
        pass
    v2 = row.get("duration_s")
    try:
        if pd.notna(v2):
            return float(v2)
    except Exception:
        pass
    return None


def auto_use_flag(row: pd.Series, min_span_s: float = 60.0) -> tuple[str, str]:
    """
    Return (use_flag, reason).
    use_flag in {yes, maybe, no}
    """
    # Hard prerequisites
    if str(row.get("scan_status", "")) != "OK":
        return "no", "scan_not_ok"

    if not bool(row.get("has_meta_json", False)):
        return "no", "meta_missing"

    if row.get("close_ok") not in (True, "TRUE", "True", 1):
        # allow missing close_ok to be maybe
        if pd.isna(row.get("close_ok")):
            return "maybe", "close_ok_unknown"
        return "no", "close_not_ok"

    qc = str(row.get("qc_overall", "UNKNOWN")).upper().strip()
    if qc == "FAIL":
        return "no", "qc_fail"
    if qc == "UNKNOWN":
        # don't drop, but mark maybe
        return "maybe", "qc_unknown"

    span = pick_active_span(row)
    if span is None:
        return "maybe", "span_unknown"
    if span < min_span_s:
        return "no", f"too_short(<{min_span_s}s)"

    # OK/WARN with sufficient span
    if qc in ("OK", "WARN"):
        return "yes", f"qc_{qc.lower()}"

    return "maybe", "qc_other"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-root", default=r"D:\701lab\work")
    ap.add_argument("--in-parquet", default="")
    ap.add_argument("--also-csv", action="store_true")
    ap.add_argument("--min-span-s", type=float, default=60.0, help="minimum active span to accept run")
    args = ap.parse_args()

    work_root = Path(args.work_root)
    staging = work_root / "phaseB" / "derived" / "b1" / "_staging"
    derived_b1 = work_root / "phaseB" / "derived" / "b1"
    derived_b1.mkdir(parents=True, exist_ok=True)
    staging.mkdir(parents=True, exist_ok=True)

    in_parquet = Path(args.in_parquet) if args.in_parquet else (staging / "b1_3_runs_with_volume.parquet")
    if not in_parquet.exists():
        raise SystemExit(f"[NG] input not found: {in_parquet}")

    df = pd.read_parquet(in_parquet)

    # Normalize enable flags -> has_* booleans (B2 filters will love this)
    df["has_imu"] = df.get("imu_enable").fillna(False).astype(bool)
    df["has_audio"] = df.get("audio_enable").fillna(False).astype(bool)
    df["has_polar"] = df.get("polar_enable").fillna(False).astype(bool)
    # gps/temp are not in meta env; infer from segments presence if needed (lightweight)
    df["has_gps"] = True  # safe default; refine later in B2 if needed
    df["has_temp"] = True

    # Active span (preferred)
    df["active_span_s"] = df.apply(pick_active_span, axis=1)

    # Auto flags
    out_flags = df.apply(lambda r: auto_use_flag(r, min_span_s=args.min_span_s), axis=1, result_type="expand")
    df["use_flag"] = out_flags[0]
    df["use_reason"] = out_flags[1]

    df["b1_4_ingested_at_iso_utc"] = datetime.now(timezone.utc).isoformat()

    # Write editable CSV (minimal columns)
    flags_cols = [
        "run_id",
        "use_flag",
        "use_reason",
        "qc_overall",
        "active_span_s",
        "duration_s",
        "close_ok",
        "close_reason",
        "version",
    ]
    flags_csv = derived_b1 / "run_flags.csv"
    df[flags_cols].to_csv(flags_csv, index=False, encoding="utf-8-sig")

    out_parquet = staging / "b1_4_runs_flagged.parquet"
    df.to_parquet(out_parquet, index=False)
    if args.also_csv:
        out_csv = out_parquet.with_suffix(".csv")
        df.to_csv(out_csv, index=False, encoding="utf-8-sig")

    print(f"[OK] input : {in_parquet}")
    print(f"[OK] wrote : {flags_csv}")
    print(f"[OK] wrote : {out_parquet}")
    if args.also_csv:
        print(f"[OK] wrote : {out_csv}")

    print("[INFO] use_flag counts:")
    print(df["use_flag"].value_counts(dropna=False).to_string())

    preview_cols = ["run_id", "qc_overall", "active_span_s", "use_flag", "use_reason"]
    print("[INFO] preview:")
    print(df[preview_cols].to_string(index=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
