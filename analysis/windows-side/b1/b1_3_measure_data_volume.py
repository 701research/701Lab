#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase B1-3: Measure data volume + active span (lightweight)

Input:
  work/phaseB/derived/b1/_staging/b1_2_runs_with_qc.parquet

Reads (per run):
  immutable/runs/run_*/unified.csv                      (NO full read)
  immutable/runs/run_*/derived/segments_run.csv         (preferred, lightweight)

Output:
  work/phaseB/derived/b1/_staging/b1_3_runs_with_volume.parquet
  (+ optional CSV)

Run:
  conda activate phaseb
  python b1_3_measure_data_volume.py --also-csv
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd


def _count_lines_fast(p: Path) -> Tuple[Optional[int], Optional[str]]:
    """Count lines without loading whole file into memory."""
    try:
        n = 0
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                n += chunk.count(b"\n")
        # If file ends without newline, this still counts correctly for CSVs usually ending with \n.
        return int(n), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _read_first_twall(p: Path) -> Tuple[Optional[str], Optional[str]]:
    """Read t_wall from the first data row of unified.csv (after header)."""
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            r = csv.reader(f)
            header = next(r, None)
            if not header:
                return None, "empty_file"
            # Expect header includes 't_wall'
            try:
                i_twall = header.index("t_wall")
            except ValueError:
                return None, "header_missing_t_wall"
            row1 = next(r, None)
            if not row1:
                return None, "no_data_rows"
            return row1[i_twall], None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _read_last_twall(p: Path) -> Tuple[Optional[str], Optional[str]]:
    """Read t_wall from the last non-empty data row of unified.csv using a tail approach."""
    try:
        # Read last ~64KB and find last line
        with p.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            block = 65536
            seek = max(0, size - block)
            f.seek(seek)
            data = f.read()
        text = data.decode("utf-8", errors="replace")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if len(lines) < 2:
            return None, "too_few_lines"
        # Last line should be a data row; but tail may include header if file is small
        last = lines[-1]
        # Need header to locate t_wall index
        with p.open("r", encoding="utf-8", newline="") as f:
            header = next(csv.reader(f), None)
        if not header:
            return None, "empty_file"
        try:
            i_twall = header.index("t_wall")
        except ValueError:
            return None, "header_missing_t_wall"
        parts = list(csv.reader([last]))[0]
        if i_twall >= len(parts):
            return None, "last_row_short"
        return parts[i_twall], None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _to_float(x: Optional[str]) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None


def _segments_run_active_span(seg_path: Path) -> Tuple[Optional[float], Optional[str]]:
    """
    Sum durations from segments_run.csv.
    We keep it flexible: look for (t0,t1) or (start,end) columns.
    """
    try:
        df = pd.read_csv(seg_path)
        # candidate column pairs
        pairs = [
            ("t0", "t1"),
            ("start", "end"),
            ("start_s", "end_s"),
            ("t_start", "t_end"),
        ]
        for a, b in pairs:
            if a in df.columns and b in df.columns:
                t0 = pd.to_numeric(df[a], errors="coerce")
                t1 = pd.to_numeric(df[b], errors="coerce")
                dur = (t1 - t0).clip(lower=0)
                s = float(dur.sum(skipna=True))
                return s, None
        return None, "no_expected_columns"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-root", default=r"D:\701lab\work")
    ap.add_argument("--in-parquet", default="")
    ap.add_argument("--out-parquet", default="")
    ap.add_argument("--also-csv", action="store_true")
    args = ap.parse_args()

    work_root = Path(args.work_root)
    staging = work_root / "phaseB" / "derived" / "b1" / "_staging"
    in_parquet = Path(args.in_parquet) if args.in_parquet else (staging / "b1_2_runs_with_qc.parquet")
    out_parquet = Path(args.out_parquet) if args.out_parquet else (staging / "b1_3_runs_with_volume.parquet")
    out_parquet.parent.mkdir(parents=True, exist_ok=True)

    if not in_parquet.exists():
        raise SystemExit(f"[NG] input not found: {in_parquet}")

    df = pd.read_parquet(in_parquet)

    unified_rows = []
    first_twall = []
    last_twall = []
    active_span_unified = []
    unified_err = []

    seg_run_span = []
    seg_run_err = []
    has_segments_run = []

    for _, row in df.iterrows():
        run_path = Path(row["run_path_immutable"])

        unified_path = run_path / "unified.csv"
        seg_path = run_path / "derived" / "segments_run.csv"

        # unified.csv stats
        if unified_path.exists():
            n, e1 = _count_lines_fast(unified_path)
            # subtract header line if present
            n_data = (n - 1) if (n is not None and n > 0) else n
            ft, e2 = _read_first_twall(unified_path)
            lt, e3 = _read_last_twall(unified_path)

            unified_rows.append(n_data)
            first_twall.append(ft)
            last_twall.append(lt)

            f = _to_float(ft)
            l = _to_float(lt)
            active_span_unified.append((l - f) if (f is not None and l is not None and l >= f) else None)

            # keep one merged error string
            errs = [x for x in [e1, e2, e3] if x]
            unified_err.append(";".join(errs) if errs else None)
        else:
            unified_rows.append(None)
            first_twall.append(None)
            last_twall.append(None)
            active_span_unified.append(None)
            unified_err.append("unified_missing")

        # segments_run stats
        if seg_path.exists():
            s, es = _segments_run_active_span(seg_path)
            seg_run_span.append(s)
            seg_run_err.append(es)
            has_segments_run.append(True)
        else:
            seg_run_span.append(None)
            seg_run_err.append("segments_run_missing")
            has_segments_run.append(False)

    out = df.copy()
    out["unified_rows"] = unified_rows
    out["first_t_wall"] = first_twall
    out["last_t_wall"] = last_twall
    out["active_span_s_unified"] = active_span_unified
    out["unified_scan_error"] = unified_err

    out["has_segments_run"] = has_segments_run
    out["active_span_s_segments_run"] = seg_run_span
    out["segments_run_error"] = seg_run_err

    out["b1_3_ingested_at_iso_utc"] = datetime.now(timezone.utc).isoformat()

    out.to_parquet(out_parquet, index=False)
    if args.also_csv:
        out_csv = out_parquet.with_suffix(".csv")
        out.to_csv(out_csv, index=False, encoding="utf-8-sig")

    print(f"[OK] input : {in_parquet}")
    print(f"[OK] wrote : {out_parquet}")
    if args.also_csv:
        print(f"[OK] wrote : {out_csv}")

    # quick one-line summary
    cols = ["run_id", "unified_rows", "active_span_s_unified", "active_span_s_segments_run", "unified_scan_error", "segments_run_error"]
    print("[INFO] preview:")
    print(out[cols].to_string(index=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
