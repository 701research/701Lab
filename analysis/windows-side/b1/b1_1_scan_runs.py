#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase B1-1: Scan runs + extract minimal meta (lightweight)

- Reads: D:\701lab\immutable\runs\run_*\meta.json  (read-only)
- Writes: D:\701lab\work\phaseB\derived\b1\_staging\b1_1_runs_base.parquet
          (+ optional CSV for quick viewing)

Design goals
- Do NOT recurse into raw/ or derived/ inside each run
- Never load large files
- Never fail the whole scan if one run is broken (record scan_status/error and continue)

Run (PowerShell):
  conda activate phaseb
  python b1_1_scan_runs.py

Optional:
  python b1_1_scan_runs.py --immutable-root D:\701lab\immutable --work-root D:\701lab\work
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd


def _epoch_to_iso_utc(epoch: Optional[float]) -> Optional[str]:
    if epoch is None:
        return None
    try:
        return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat()
    except Exception:
        return None


def _safe_read_json(p: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _get_nested(d: Dict[str, Any], *keys: str) -> Any:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def _truthy_enable(v: Any) -> Optional[bool]:
    """
    Interpret enable flags like "1"/"0", "true"/"false", True/False.
    Returns None if value is missing/unknown.
    """
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in {"1", "true", "yes", "on"}:
            return True
        if s in {"0", "false", "no", "off"}:
            return False
    return None


@dataclass
class RunRow:
    # Identity / references
    run_id: str
    run_dirname: str
    run_path_immutable: str
    meta_path: str

    # Meta basics
    run_dir_pi: Optional[str]  # meta.run_dir (Pi-side path) - for provenance only
    version: Optional[str]

    # Open/close (wall time)
    open_t_wall_epoch: Optional[float]
    open_t_wall_iso_utc: Optional[str]
    close_t_wall_epoch: Optional[float]
    close_t_wall_iso_utc: Optional[str]
    duration_s: Optional[float]

    close_ok: Optional[bool]
    close_reason: Optional[str]

    # Optional: GPS at start
    gps_fix_at_start: Optional[bool]
    gps_utc_at_start: Optional[str]

    # Optional: sensor enable flags (from env)
    imu_enable: Optional[bool]
    audio_enable: Optional[bool]
    polar_enable: Optional[bool]

    # Existence checks (only run-root level)
    has_qc_report_md: bool
    has_qc_json: bool
    has_provenance_json: bool
    has_events: bool
    has_segments: bool
    has_unified_csv: bool

    # Scan bookkeeping
    ingested_at_iso_utc: str
    scan_status: str
    scan_error: Optional[str]


def build_row(run_dir: Path) -> RunRow:
    run_dirname = run_dir.name

    meta_path = _find_meta_json(run_dir)


    # defaults
    now_iso = datetime.now(timezone.utc).isoformat()

    # existence flags (fixed locations for current layout)
    has_qc_report_md = (run_dir / "derived" / "qc_report.md").exists()
    has_qc_json = (run_dir / "derived" / "qc_report.json").exists()  # NOTE: name differs
    has_prov = (run_dir / "derived" / "provenance.json").exists()

    has_events = (run_dir / "derived" / "events.csv").exists() or (run_dir / "derived" / "events.json").exists()
    # segments are split per sensor; we just check presence of any segments_* file
    has_segments = any(p.exists() for p in (run_dir / "derived").glob("segments_*.csv"))

    has_unified = (run_dir / "unified.csv").exists()


    # If no meta.json, still create a row
    if meta_path is None:
        expected_meta = run_dir / "meta" / "meta.json"
        return RunRow(
            run_id=run_dirname,  # fallback: dirname
            run_dirname=run_dirname,
            run_path_immutable=str(run_dir),
             meta_path=str(expected_meta), 
            run_dir_pi=None,
            version=None,
            open_t_wall_epoch=None,
            open_t_wall_iso_utc=None,
            close_t_wall_epoch=None,
            close_t_wall_iso_utc=None,
            duration_s=None,
            close_ok=None,
            close_reason=None,
            gps_fix_at_start=None,
            gps_utc_at_start=None,
            imu_enable=None,
            audio_enable=None,
            polar_enable=None,
            has_qc_report_md=has_qc_report_md,
            has_qc_json=has_qc_json,
            has_provenance_json=has_prov,
            has_events=has_events,
            has_segments=has_segments,
            has_unified_csv=has_unified,
            ingested_at_iso_utc=now_iso,
            scan_status="META_MISSING",
            scan_error=None,
        )

    meta, err = _safe_read_json(meta_path)
    if meta is None:
        return RunRow(
            run_id=run_dirname,
            run_dirname=run_dirname,
            run_path_immutable=str(run_dir),
            meta_path=str(meta_path),
            run_dir_pi=None,
            version=None,
            open_t_wall_epoch=None,
            open_t_wall_iso_utc=None,
            close_t_wall_epoch=None,
            close_t_wall_iso_utc=None,
            duration_s=None,
            close_ok=None,
            close_reason=None,
            gps_fix_at_start=None,
            gps_utc_at_start=None,
            imu_enable=None,
            audio_enable=None,
            polar_enable=None,
            has_qc_report_md=has_qc_report_md,
            has_qc_json=has_qc_json,
            has_provenance_json=has_prov,
            has_events=has_events,
            has_segments=has_segments,
            has_unified_csv=has_unified,
            ingested_at_iso_utc=now_iso,
            scan_status="META_READ_ERROR",
            scan_error=err,
        )

    # identity
    run_id = meta.get("run_id") or run_dirname
    run_dir_pi = meta.get("run_dir")
    version = meta.get("version")

    # open/close
    open_t_wall = _get_nested(meta, "open", "t_wall")
    close_t_wall = _get_nested(meta, "close", "t_wall")
    open_iso = _epoch_to_iso_utc(open_t_wall)
    close_iso = _epoch_to_iso_utc(close_t_wall)

    duration_s = None
    try:
        if open_t_wall is not None and close_t_wall is not None:
            duration_s = float(close_t_wall) - float(open_t_wall)
            if duration_s < 0:
                duration_s = None
    except Exception:
        duration_s = None

    close_ok = _get_nested(meta, "close", "ok")
    if isinstance(close_ok, str):
        # just in case
        close_ok = _truthy_enable(close_ok)

    close_reason = _get_nested(meta, "close", "reason")

    # optional GPS at start
    gps_fix_at_start = _get_nested(meta, "open", "gps_fix_at_start")
    if isinstance(gps_fix_at_start, str):
        gps_fix_at_start = _truthy_enable(gps_fix_at_start)
    gps_utc_at_start = _get_nested(meta, "open", "gps_utc_at_start")

    # env enables (optional)
    env = meta.get("env") if isinstance(meta.get("env"), dict) else {}
    imu_enable = _truthy_enable(env.get("IMU_ENABLE"))
    audio_enable = _truthy_enable(env.get("AUDIO_ENABLE"))
    polar_enable = _truthy_enable(env.get("POLAR_ENABLE"))

    # status
    scan_status = "OK"
    scan_error = None
    # If key fields missing, mark as incomplete but not error
    if meta.get("run_id") is None or meta.get("run_dir") is None:
        scan_status = "META_INCOMPLETE"

    return RunRow(
        run_id=str(run_id),
        run_dirname=run_dirname,
        run_path_immutable=str(run_dir),
        meta_path=str(meta_path),
        run_dir_pi=str(run_dir_pi) if run_dir_pi is not None else None,
        version=str(version) if version is not None else None,
        open_t_wall_epoch=float(open_t_wall) if open_t_wall is not None else None,
        open_t_wall_iso_utc=open_iso,
        close_t_wall_epoch=float(close_t_wall) if close_t_wall is not None else None,
        close_t_wall_iso_utc=close_iso,
        duration_s=duration_s,
        close_ok=close_ok if isinstance(close_ok, bool) else (close_ok if close_ok is None else bool(close_ok)),
        close_reason=str(close_reason) if close_reason is not None else None,
        gps_fix_at_start=gps_fix_at_start if isinstance(gps_fix_at_start, bool) else (gps_fix_at_start if gps_fix_at_start is None else bool(gps_fix_at_start)),
        gps_utc_at_start=str(gps_utc_at_start) if gps_utc_at_start is not None else None,
        imu_enable=imu_enable,
        audio_enable=audio_enable,
        polar_enable=polar_enable,
        has_qc_report_md=has_qc_report_md,
        has_qc_json=has_qc_json,
        has_provenance_json=has_prov,
        has_events=has_events,
        has_segments=has_segments,
        has_unified_csv=has_unified,
        ingested_at_iso_utc=now_iso,
        scan_status=scan_status,
        scan_error=scan_error,
    )

def _find_meta_json(run_dir: Path) -> Optional[Path]:
    """
    Find meta.json in a fixed set of candidate locations (non-recursive).
    We keep this lightweight and deterministic for B1.
    """
    candidates = [
        run_dir / "meta.json",
        run_dir / "meta" / "meta.json",              # <-- current Windows layout
        run_dir / "derived" / "meta.json",
        run_dir / "derived" / "meta" / "meta.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--immutable-root", default=r"D:\701lab\immutable", help="Root that contains runs/")
    ap.add_argument("--work-root", default=r"D:\701lab\work", help="Root that contains phaseB/")
    ap.add_argument("--runs-subdir", default="runs", help="Subdir under immutable-root that holds run_*")
    ap.add_argument("--out-parquet", default="", help="Override output parquet path")
    ap.add_argument("--also-csv", action="store_true", help="Also write CSV next to parquet")
    args = ap.parse_args()

    immutable_root = Path(args.immutable_root)
    runs_root = immutable_root / args.runs_subdir
    work_root = Path(args.work_root)
    out_dir = work_root / "phaseB" / "derived" / "b1" / "_staging"
    out_dir.mkdir(parents=True, exist_ok=True)

    out_parquet = Path(args.out_parquet) if args.out_parquet else (out_dir / "b1_1_runs_base.parquet")
    out_csv = out_parquet.with_suffix(".csv")

    if not runs_root.exists():
        raise SystemExit(f"[NG] runs root not found: {runs_root}")

    # enumerate run dirs (non-recursive)
    run_dirs = sorted(
        [p for p in runs_root.glob("run_*") if p.is_dir()],
        key=lambda p: p.name,
    )

    rows = []
    for rd in run_dirs:
        try:
            rows.append(asdict(build_row(rd)))
        except Exception as e:
            # absolute fallback: never crash the scan
            now_iso = datetime.now(timezone.utc).isoformat()
            rows.append(
                asdict(
                    RunRow(
                        run_id=rd.name,
                        run_dirname=rd.name,
                        run_path_immutable=str(rd),
                        meta_path=str(rd / "meta.json"),
                        run_dir_pi=None,
                        version=None,
                        open_t_wall_epoch=None,
                        open_t_wall_iso_utc=None,
                        close_t_wall_epoch=None,
                        close_t_wall_iso_utc=None,
                        duration_s=None,
                        close_ok=None,
                        close_reason=None,
                        gps_fix_at_start=None,
                        gps_utc_at_start=None,
                        imu_enable=None,
                        audio_enable=None,
                        polar_enable=None,
                        has_qc_report_md=(rd / "qc_report.md").exists(),
                        has_qc_json=(rd / "qc.json").exists(),
                        has_provenance_json=(rd / "provenance.json").exists(),
                        has_events=False,
                        has_segments=False,
                        has_unified_csv=(rd / "unified.csv").exists(),
                        ingested_at_iso_utc=now_iso,
                        scan_status="ROW_BUILD_ERROR",
                        scan_error=f"{type(e).__name__}: {e}",
                    )
                )
            )

    df = pd.DataFrame(rows)

    # A few convenience columns (still B1-1-safe)
    df["has_meta_json"] = df["scan_status"].ne("META_MISSING")
    df["closed_normally"] = df["close_ok"].fillna(False)

    # write
    df.to_parquet(out_parquet, index=False)
    if args.also_csv:
        df.to_csv(out_csv, index=False, encoding="utf-8-sig")

    print(f"[OK] scanned runs: {len(df)}")
    print(f"[OK] wrote: {out_parquet}")
    if args.also_csv:
        print(f"[OK] wrote: {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
