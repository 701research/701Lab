#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
701 Lab A5: Run Index (簡易台帳) generator

What this does
- Scan runs_root (default: /media/seven_zero_one/MF-SU2C/701lab_data/runs) for run_*
- For each run, read (if present):
    derived/qc_report.json
    derived/segments_meta.json
    derived/segments_*.csv (gps/polar/audio)
    derived/events_meta.json
    meta/meta.json
    unified.csv (fallback: compute bounds if segments_meta missing)
- Write a single CSV: <runs_root>/derived/runs_index.csv

Design
- Pi-side deterministic, stdlib only
- Robust to missing derived artifacts (fills blanks)
- Good enough for "Windowsへ持っていくrunの選別" が目的

Usage
  python3 a5_make_run_index.py
  python3 a5_make_run_index.py --runs-root /media/seven_zero_one/MF-SU2C/701lab_data/runs
  python3 a5_make_run_index.py --output /path/to/runs_index.csv
  python3 a5_make_run_index.py --limit 20 --sort mtime
  python3 a5_make_run_index.py --print

Outputs
  <runs_root>/derived/runs_index.csv   (default)
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


DEFAULT_RUNS_ROOT = "/media/seven_zero_one/MF-SU2C/701lab_data/runs"


def iso_now() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


def safe_float(x: str) -> Optional[float]:
    try:
        v = float(x)
        return v if v == v else None
    except Exception:
        return None


def safe_int(x: str) -> Optional[int]:
    try:
        return int(float(x))
    except Exception:
        return None


def read_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def scan_unified_bounds(unified_path: Path) -> Tuple[Optional[float], Optional[float]]:
    """Fallback: compute t_mono min/max from unified.csv."""
    if not unified_path.exists():
        return None, None
    t_min = None
    t_max = None
    try:
        with unified_path.open("r", encoding="utf-8", newline="") as f:
            r = csv.DictReader(f)
            if not r.fieldnames or "t_mono" not in r.fieldnames:
                return None, None
            for row in r:
                t = safe_float(row.get("t_mono", ""))
                if t is None:
                    continue
                if t_min is None or t < t_min:
                    t_min = t
                if t_max is None or t > t_max:
                    t_max = t
        return t_min, t_max
    except Exception:
        return None, None


def sum_segments_csv(path: Path) -> Optional[float]:
    """Sum (t_end - t_start) for rows in segments_*.csv."""
    if not path.exists():
        return None
    total = 0.0
    any_row = False
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            r = csv.DictReader(f)
            if not r.fieldnames or "t_start" not in r.fieldnames or "t_end" not in r.fieldnames:
                return None
            for row in r:
                a = safe_float(row.get("t_start", ""))
                b = safe_float(row.get("t_end", ""))
                if a is None or b is None:
                    continue
                if b > a:
                    total += (b - a)
                    any_row = True
        return total if any_row else 0.0
    except Exception:
        return None


def first_segment_bounds(path: Path) -> Tuple[Optional[float], Optional[float]]:
    """Read first segment's t_start/t_end from segments_*.csv."""
    if not path.exists():
        return None, None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            r = csv.DictReader(f)
            for row in r:
                a = safe_float(row.get("t_start", ""))
                b = safe_float(row.get("t_end", ""))
                return a, b
        return None, None
    except Exception:
        return None, None


def pick_env_keys(env: dict) -> dict:
    """Keep only keys that help selection (small & stable)."""
    keep = [
        "IMU_ENABLE", "AUDIO_ENABLE", "POLAR_ENABLE", "GPS_ENABLE",
        "IMU_PORT", "AUDIO_DEVICE", "POLAR_DEVICE",
        "AUDIO_RATE", "AUDIO_CHANNELS",
    ]
    out = {}
    for k in keep:
        if k in env:
            out[k] = env.get(k)
    return out


def collect_run_row(run_dir: Path) -> Dict[str, object]:
    derived = run_dir / "derived"
    meta_dir = run_dir / "meta"

    qc = read_json(derived / "qc_report.json")
    segm = read_json(derived / "segments_meta.json")
    evm = read_json(derived / "events_meta.json")
    meta = read_json(meta_dir / "meta.json")

    # timestamps & sizes
    st = run_dir.stat()
    mtime_iso = dt.datetime.fromtimestamp(st.st_mtime).replace(microsecond=0).isoformat()

    # bounds/duration
    t_min = None
    t_max = None
    dur = None
    if isinstance(segm, dict):
        b = segm.get("bounds") or {}
        t_min = b.get("t_min")
        t_max = b.get("t_max")
        dur = b.get("duration_sec")
    if t_min is None or t_max is None:
        umin, umax = scan_unified_bounds(run_dir / "unified.csv")
        t_min = t_min if t_min is not None else umin
        t_max = t_max if t_max is not None else umax
        if (t_min is not None) and (t_max is not None):
            dur = float(t_max) - float(t_min)

    # qc summary
    qc_overall = None
    qc_audio_level = None
    qc_audio_msg = None

    if isinstance(qc, dict):
        qc_overall = qc.get("overall")
        c_audio = (qc.get("checks") or {}).get("audio_basic") or {}
        if isinstance(c_audio, dict):
            qc_audio_level = c_audio.get("level")
            qc_audio_msg = c_audio.get("message")

    # --- FIX 1) audio_duration_diff_sec: prefer segments_meta.json (stable), fallback to qc_report.json ---
    audio_diff = None

    # 1) Prefer segments_meta.json
    if isinstance(segm, dict):
        a = segm.get("audio") or {}
        if isinstance(a, dict):
            audio_diff = a.get("duration_diff_sec")

    # 2) Fallback to qc_report.json (version-dependent nesting)
    if audio_diff is None and isinstance(qc, dict):
        c_audio = (qc.get("checks") or {}).get("audio_basic") or {}
        if isinstance(c_audio, dict):
            js = c_audio.get("json") or {}
            if isinstance(js, dict):
                audio_diff = js.get("duration_diff_sec") or js.get("duration_diff") or None

    # segments sums (prefer CSV sums because definitive for "effective duration")
    gps_fix_dur = sum_segments_csv(derived / "segments_gps.csv")
    polar_dur = sum_segments_csv(derived / "segments_polar.csv")
    audio_dur = sum_segments_csv(derived / "segments_audio.csv")
    imu_dur = sum_segments_csv(derived / "segments_imu.csv")  # usually full run

    # first/last of polar connect/disconnect are better in events, but keep simple counts
    exc_count = None
    polar_restart = None
    if isinstance(evm, dict):
        counts = evm.get("counts") or {}
        stc = counts.get("status") or {}
        if isinstance(stc, dict):
            exc_count = stc.get("EXCEPTION")
            polar_restart = stc.get("POLAR_RESTART")

    # meta env
    env_small = None
    if isinstance(meta, dict):
        env = (meta.get("env") or {})
        if isinstance(env, dict):
            env_small = pick_env_keys(env)

    # --- FIX 2) env: CSV-friendly string (no commas) to keep `column -s,` stable ---
    env_str = ""
    if isinstance(env_small, dict) and env_small:
        parts = []
        for k, v in env_small.items():
            vv = "" if v is None else str(v)
            vv = vv.replace(",", ";")  # avoid comma that breaks `column -s,`
            parts.append(f"{k}={vv}")
        env_str = "|".join(parts)

    # file existence hints
    has_unified = (run_dir / "unified.csv").exists()
    has_status = (run_dir / "status.csv").exists()
    has_audio = (run_dir / "raw" / "audio.wav").exists()
    has_imu_bin = (run_dir / "raw" / "imu_bwt901cl.bin").exists()

    # bytes (quick)
    def fsize(p: Path) -> Optional[int]:
        try:
            return p.stat().st_size if p.exists() else None
        except Exception:
            return None

    row: Dict[str, object] = {
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "mtime": mtime_iso,

        "duration_sec": dur,
        "t_min": t_min,
        "t_max": t_max,

        "qc_overall": qc_overall,
        "qc_audio_level": qc_audio_level,
        "qc_audio_msg": qc_audio_msg,
        "audio_duration_diff_sec": audio_diff,

        "gps_fix_dur_sec": gps_fix_dur,
        "polar_dur_sec": polar_dur,
        "audio_dur_sec": audio_dur,
        "imu_dur_sec": imu_dur,

        "exceptions": exc_count,
        "polar_restarts": polar_restart,

        "has_unified": int(bool(has_unified)),
        "has_status": int(bool(has_status)),
        "has_audio_wav": int(bool(has_audio)),
        "has_imu_bin": int(bool(has_imu_bin)),

        "bytes_unified": fsize(run_dir / "unified.csv"),
        "bytes_status": fsize(run_dir / "status.csv"),
        "bytes_audio_wav": fsize(run_dir / "raw" / "audio.wav"),
        "bytes_imu_bin": fsize(run_dir / "raw" / "imu_bwt901cl.bin"),

        "env": env_str,
    }
    return row



def list_runs(runs_root: Path) -> List[Path]:
    runs = [p for p in runs_root.glob("run_*") if p.is_dir()]
    return runs


def sort_runs(runs: List[Path], mode: str) -> List[Path]:
    if mode == "mtime":
        return sorted(runs, key=lambda p: p.stat().st_mtime, reverse=True)
    if mode == "name":
        return sorted(runs, key=lambda p: p.name)
    return runs


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    if not rows:
        # still write header for consistency
        cols = [
            "run_id", "run_dir", "mtime",
            "duration_sec", "t_min", "t_max",
            "qc_overall", "qc_audio_level", "qc_audio_msg", "audio_duration_diff_sec",
            "gps_fix_dur_sec", "polar_dur_sec", "audio_dur_sec", "imu_dur_sec",
            "exceptions", "polar_restarts",
            "has_unified", "has_status", "has_audio_wav", "has_imu_bin",
            "bytes_unified", "bytes_status", "bytes_audio_wav", "bytes_imu_bin",
            "env",
        ]
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
        return

    cols = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-root", default=DEFAULT_RUNS_ROOT, help="runs root containing run_*")
    ap.add_argument("--output", default=None, help="output csv path (default: <runs_root>/derived/runs_index.csv)")
    ap.add_argument("--sort", default="mtime", choices=["mtime", "name"], help="sort order")
    ap.add_argument("--limit", type=int, default=0, help="limit number of runs (0=all)")
    ap.add_argument("--print", action="store_true", help="print output path only")
    args = ap.parse_args()

    runs_root = Path(args.runs_root)
    if not runs_root.exists():
        print(f"ERROR: runs_root not found: {runs_root}", file=sys.stderr)
        return 2

    out_path = Path(args.output) if args.output else (runs_root / "derived" / "runs_index.csv")
    ensure_dir(out_path.parent)

    runs = sort_runs(list_runs(runs_root), args.sort)
    if args.limit and args.limit > 0:
        runs = runs[: args.limit]

    rows: List[Dict[str, object]] = []
    for rd in runs:
        try:
            rows.append(collect_run_row(rd))
        except Exception as e:
            # keep scanning; write a minimal row with error
            rows.append({
                "run_id": rd.name,
                "run_dir": str(rd),
                "mtime": "",
                "duration_sec": "",
                "t_min": "",
                "t_max": "",
                "qc_overall": "ERR",
                "qc_audio_level": "",
                "qc_audio_msg": f"index_error:{e}",
                "audio_duration_diff_sec": "",
                "gps_fix_dur_sec": "",
                "polar_dur_sec": "",
                "audio_dur_sec": "",
                "imu_dur_sec": "",
                "exceptions": "",
                "polar_restarts": "",
                "has_unified": int((rd / "unified.csv").exists()),
                "has_status": int((rd / "status.csv").exists()),
                "has_audio_wav": int((rd / "raw" / "audio.wav").exists()),
                "has_imu_bin": int((rd / "raw" / "imu_bwt901cl.bin").exists()),
                "bytes_unified": "",
                "bytes_status": "",
                "bytes_audio_wav": "",
                "bytes_imu_bin": "",
                "env": "",
            })

    # write
    write_csv(out_path, rows)

    if args.print:
        print(out_path)
    else:
        print(f"Wrote run index: {out_path} (rows={len(rows)})  created_at={iso_now()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
