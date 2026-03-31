#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase B1-5 (cross-run only): Finalize B1 outputs
- Freeze run_summary as the single entry point for B2/B3
- Create only distribution-level figures (NOT per-run signal plots)
- Write a concise markdown report

Input:
  work/phaseB/derived/b1/_staging/b1_4_runs_flagged.parquet

Outputs:
  work/phaseB/derived/b1/run_summary.parquet
  work/phaseB/derived/b1/run_summary.csv
  work/phaseB/figures/b1/qc_overall_counts.png
  work/phaseB/figures/b1/active_span_hist.png
  work/phaseB/figures/b1/use_flag_counts.png
  work/phaseB/reports/b1_summary.md

Run:
  conda activate phaseb
  python b1_5_finalize_and_report.py
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import pandas as pd
import matplotlib.pyplot as plt


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _pick_columns(df: pd.DataFrame, cols: List[str]) -> List[str]:
    return [c for c in cols if c in df.columns]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-root", default=r"D:\701lab\work")
    ap.add_argument("--in-parquet", default="")
    ap.add_argument("--no-figures", action="store_true", help="Skip figure generation")
    args = ap.parse_args()

    work_root = Path(args.work_root)
    staging = work_root / "phaseB" / "derived" / "b1" / "_staging"
    derived_b1 = work_root / "phaseB" / "derived" / "b1"
    figures_b1 = work_root / "phaseB" / "figures" / "b1"
    reports_dir = work_root / "phaseB" / "reports"

    _ensure_dir(staging)
    _ensure_dir(derived_b1)
    _ensure_dir(figures_b1)
    _ensure_dir(reports_dir)

    in_parquet = Path(args.in_parquet) if args.in_parquet else (staging / "b1_4_runs_flagged.parquet")
    if not in_parquet.exists():
        raise SystemExit(f"[NG] input not found: {in_parquet}")

    df = pd.read_parquet(in_parquet).copy()

    # ---- Freeze interface for B2/B3 (stable schema) ----
    # Keep only cross-run, lightweight columns (1 run = 1 row)
    wanted = [
        "run_id",
        "run_path_immutable",
        "meta_path",
        "version",
        "open_t_wall_iso_utc",
        "close_t_wall_iso_utc",
        "duration_s",
        "active_span_s",
        "unified_rows",
        "qc_overall",
        "qc_reasons",
        "qc_source",
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
    final_cols = _pick_columns(df, wanted)
    out = df[final_cols].copy()

    # Sort: by start time if available
    if "open_t_wall_iso_utc" in out.columns:
        out = out.sort_values(["open_t_wall_iso_utc", "run_id"], kind="mergesort")
    else:
        out = out.sort_values(["run_id"], kind="mergesort")

    finalized_at = datetime.now(timezone.utc).isoformat()
    out["b1_finalized_at_iso_utc"] = finalized_at

    # Write run_summary
    out_parquet = derived_b1 / "run_summary.parquet"
    out_csv = derived_b1 / "run_summary.csv"
    out.to_parquet(out_parquet, index=False)
    out.to_csv(out_csv, index=False, encoding="utf-8-sig")

    # ---- Figures (distribution only) ----
    fig_paths = []

    if not args.no_figures:
        # QC counts
        if "qc_overall" in out.columns:
            counts = out["qc_overall"].fillna("UNKNOWN").value_counts()
            plt.figure()
            counts.plot(kind="bar")
            plt.title("QC overall counts")
            plt.xlabel("qc_overall")
            plt.ylabel("runs")
            plt.tight_layout()
            p = figures_b1 / "qc_overall_counts.png"
            plt.savefig(p, dpi=150)
            plt.close()
            fig_paths.append(p.name)

        # active span histogram
        if "active_span_s" in out.columns:
            x = pd.to_numeric(out["active_span_s"], errors="coerce").dropna()
            plt.figure()
            if len(x) > 0:
                plt.hist(x)
            plt.title("Active span distribution (s)")
            plt.xlabel("active_span_s")
            plt.ylabel("runs")
            plt.tight_layout()
            p = figures_b1 / "active_span_hist.png"
            plt.savefig(p, dpi=150)
            plt.close()
            fig_paths.append(p.name)

        # use_flag counts
        if "use_flag" in out.columns:
            counts = out["use_flag"].fillna("UNKNOWN").value_counts()
            plt.figure()
            counts.plot(kind="bar")
            plt.title("use_flag counts")
            plt.xlabel("use_flag")
            plt.ylabel("runs")
            plt.tight_layout()
            p = figures_b1 / "use_flag_counts.png"
            plt.savefig(p, dpi=150)
            plt.close()
            fig_paths.append(p.name)

    # ---- Report ----
    n_total = len(out)
    use_counts = out["use_flag"].value_counts().to_dict() if "use_flag" in out.columns else {}
    qc_counts = out["qc_overall"].fillna("UNKNOWN").value_counts().to_dict() if "qc_overall" in out.columns else {}

    report_path = reports_dir / "b1_summary.md"
    with report_path.open("w", encoding="utf-8") as f:
        f.write("# Phase B1 Summary (Cross-run Index)\n\n")
        f.write(f"- Finalized at (UTC): {finalized_at}\n")
        f.write(f"- Total runs: {n_total}\n\n")

        if use_counts:
            f.write("## use_flag counts\n\n")
            for k, v in use_counts.items():
                f.write(f"- {k}: {v}\n")
            f.write("\n")

        if qc_counts:
            f.write("## QC overall counts\n\n")
            for k, v in qc_counts.items():
                f.write(f"- {k}: {v}\n")
            f.write("\n")

        f.write("## Outputs\n\n")
        f.write("- derived/b1/run_summary.parquet (entry for B2/B3)\n")
        f.write("- derived/b1/run_summary.csv\n")
        if fig_paths:
            f.write("\n### Figures (distribution only)\n\n")
            for name in fig_paths:
                f.write(f"- figures/b1/{name}\n")
        f.write("\n## Scope note\n\n")
        f.write("- B1-5 is cross-run only: it does NOT analyze sensor signals.\n")
        f.write("- Sensor-level statistics/plots start in B2.\n")

    print(f"[OK] wrote: {out_parquet}")
    print(f"[OK] wrote: {out_csv}")
    if fig_paths:
        print(f"[OK] wrote figures under: {figures_b1}")
    print(f"[OK] wrote report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
