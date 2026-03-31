#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase B2-6: Freeze B2 outputs -> B3 entry table

Outputs:
  work/phaseB/derived/b2/b2_summary.parquet
  (optional) b2_summary.csv
  work/phaseB/reports/b2_summary.md

Run:
  conda activate phaseb
  python b2_6_freeze_b2_summary.py --also-csv
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd


def _read_parquet(p: Path) -> pd.DataFrame:
    if not p.exists():
        raise FileNotFoundError(str(p))
    return pd.read_parquet(p)


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-root", default=r"D:\701lab\work")
    ap.add_argument("--also-csv", action="store_true")
    ap.add_argument("--min-policy", default="use_and_sensor",
                    help="use_and_sensor | use_only | sensor_only | none")
    args = ap.parse_args()

    work_root = Path(args.work_root)
    b1_summary_pq = work_root / "phaseB" / "derived" / "b1" / "run_summary.parquet"
    b2_targets_pq = work_root / "phaseB" / "derived" / "b2" / "_staging" / "b2_1_targets.parquet"
    b2_quality_pq = work_root / "phaseB" / "derived" / "b2" / "b2_5_sensor_quality.parquet"

    b1 = _read_parquet(b1_summary_pq)
    b2t = _read_parquet(b2_targets_pq)
    q = _read_parquet(b2_quality_pq)

    # --- normalize keys ---
    for df in (b1, b2t, q):
        df["run_id"] = df["run_id"].astype(str)

    # --- merge ---
    # base: b1 run_summary (has use_flag, reason, qc_overall, etc.)
    m = b1.merge(b2t, on="run_id", how="left", suffixes=("", "_b2t"))
    m = m.merge(q, on="run_id", how="left", suffixes=("", "_b2q"))

    # --- derive B3 target flag ---
    policy = args.min_policy
    use_flag = m.get("use_flag")
    sensor_ok = m.get("sensor_ok_flag")

    if policy == "use_and_sensor":
        m["b3_target_flag"] = (use_flag.astype(str) == "yes") & (sensor_ok == True)
        m["b3_target_reason"] = "use_flag AND sensor_ok"
    elif policy == "use_only":
        m["b3_target_flag"] = (use_flag.astype(str) == "yes")
        m["b3_target_reason"] = "use_flag only"
    elif policy == "sensor_only":
        m["b3_target_flag"] = (sensor_ok == True)
        m["b3_target_reason"] = "sensor_ok only"
    else:
        m["b3_target_flag"] = True
        m["b3_target_reason"] = "no_filter"

    m["b2_6_frozen_at_iso_utc"] = _now_iso_utc()

    # --- keep a readable column order (keep important first, rest after) ---
    head_cols = [
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
        "sensor_ok_flag",
        "b3_target_flag",
        "b3_target_reason",
        "b2_6_frozen_at_iso_utc",
    ]
    cols = [c for c in head_cols if c in m.columns] + [c for c in m.columns if c not in head_cols]
    m = m[cols]

    # --- write outputs ---
    out_dir = work_root / "phaseB" / "derived" / "b2"
    out_dir.mkdir(parents=True, exist_ok=True)

    out_pq = out_dir / "b2_summary.parquet"
    m.to_parquet(out_pq, index=False)

    out_csv: Optional[Path] = None
    if args.also_csv:
        out_csv = out_dir / "b2_summary.csv"
        m.to_csv(out_csv, index=False, encoding="utf-8-sig")

    # --- write report (md) ---
    rep_dir = work_root / "phaseB" / "reports"
    rep_dir.mkdir(parents=True, exist_ok=True)
    rep_path = rep_dir / "b2_summary.md"

    n_all = len(m)
    n_use = int(((m.get("use_flag").astype(str) == "yes")).sum()) if "use_flag" in m.columns else 0
    n_sensor = int(((m.get("sensor_ok_flag") == True)).sum()) if "sensor_ok_flag" in m.columns else 0
    n_b3 = int(((m.get("b3_target_flag") == True)).sum()) if "b3_target_flag" in m.columns else 0

    qc_counts = m["qc_overall"].value_counts(dropna=False).to_dict() if "qc_overall" in m.columns else {}

    lines = []
    lines.append("# Phase B2 Summary (Frozen for B3)\n")
    lines.append(f"- Generated at (UTC): `{_now_iso_utc()}`")
    lines.append(f"- Policy: `{policy}`\n")
    lines.append("## Counts\n")
    lines.append(f"- runs total: **{n_all}**")
    lines.append(f"- use_flag==yes: **{n_use}**")
    lines.append(f"- sensor_ok_flag==True: **{n_sensor}**")
    lines.append(f"- b3_target_flag==True: **{n_b3}**\n")

    if qc_counts:
        lines.append("## QC overall counts (from B1)\n")
        for k, v in qc_counts.items():
            lines.append(f"- {k}: {v}")
        lines.append("")

    lines.append("## Output files\n")
    lines.append(f"- `derived/b2/b2_summary.parquet`")
    if out_csv:
        lines.append(f"- `derived/b2/b2_summary.csv`")
    lines.append(f"- `reports/b2_summary.md`\n")

    # preview table (top 20)
    #preview_cols = [c for c in ["run_id","qc_overall","use_flag","sensor_ok_flag","b3_target_flag","use_reason"] if c in m.columns]
    #if preview_cols:
        #lines.append("## Preview (top 20)\n")
        #lines.append(m[preview_cols].head(20).to_markdown(index=False))
        #lines.append("")

    rep_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"[OK] wrote: {out_pq}")
    if out_csv:
        print(f"[OK] wrote: {out_csv}")
    print(f"[OK] wrote: {rep_path}")
    print(f"[OK] b3_target_flag true: {n_b3}/{n_all}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
