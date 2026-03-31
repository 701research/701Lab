#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase B2-3: Compute basic sensor stats per run (temp/gps/polar/imu + audio health)

Inputs:
  work/phaseB/derived/b2/_staging/b2_1_targets.parquet
  work/phaseB/derived/b2/runs/<run_id>/unified_*.parquet
  work/phaseB/derived/b2/runs/<run_id>/imu_*.parquet
  work/phaseB/derived/b2/runs/<run_id>/raw_audio_health.json

Outputs:
  work/phaseB/derived/b2/runs/<run_id>/b2_3_stats.json
  work/phaseB/derived/b2/_staging/b2_3_sensor_stats_all.parquet
  (optional) ...csv

Run:
  conda activate phaseb
  python b2_3_compute_sensor_stats.py --also-csv
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


def _safe_read_parquet(p: Path) -> Optional[pd.DataFrame]:
    if not p.exists():
        return None
    return pd.read_parquet(p)


def _basic_numeric_stats(x: pd.Series) -> Dict[str, Any]:
    x = pd.to_numeric(x, errors="coerce")
    n = int(x.notna().sum())
    out: Dict[str, Any] = {"n": n}
    if n == 0:
        out.update({"mean": None, "std": None, "min": None, "p01": None, "p50": None, "p99": None, "max": None})
        return out
    xv = x.dropna().to_numpy(dtype=float)
    out.update({
        "mean": float(np.mean(xv)),
        "std": float(np.std(xv, ddof=1)) if n >= 2 else 0.0,
        "min": float(np.min(xv)),
        "p01": float(np.quantile(xv, 0.01)),
        "p50": float(np.quantile(xv, 0.50)),
        "p99": float(np.quantile(xv, 0.99)),
        "max": float(np.max(xv)),
    })
    return out


def _span_stats_from_tmono(df: pd.DataFrame, col: str = "t_mono") -> Dict[str, Any]:
    # returns first/last/span if possible
    out: Dict[str, Any] = {"first": None, "last": None, "span_s": None}
    if df is None or len(df) == 0 or col not in df.columns:
        return out
    s = pd.to_numeric(df[col], errors="coerce").dropna()
    if len(s) == 0:
        return out
    out["first"] = float(s.iloc[0])
    out["last"] = float(s.iloc[-1])
    out["span_s"] = float(s.iloc[-1] - s.iloc[0])
    return out


def _read_audio_health(p: Path) -> Dict[str, Any]:
    if not p.exists():
        return {"ok": False, "error": "missing", "path": str(p)}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {"ok": False, "error": f"json_read_error: {e}", "path": str(p)}


def _hrv_from_rr_ms(rr_ms: np.ndarray) -> Dict[str, Any]:
    """
    rr_ms: milliseconds, 1D array, already cleaned (finite, positive)
    Returns RMSSD, SDNN, pNN50 (standard definitions).
    """
    out: Dict[str, Any] = {"n_rr": int(rr_ms.size), "rmssd_ms": None, "sdnn_ms": None, "pnn50": None}
    if rr_ms.size < 2:
        return out

    diff = np.diff(rr_ms)
    out["rmssd_ms"] = float(np.sqrt(np.mean(diff * diff)))

    # SDNN: std of NN intervals
    out["sdnn_ms"] = float(np.std(rr_ms, ddof=1)) if rr_ms.size >= 2 else 0.0

    # pNN50: proportion of successive diffs > 50ms
    out["pnn50"] = float(np.mean(np.abs(diff) > 50.0))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-root", default=r"D:\701lab\work")
    ap.add_argument("--run-id", default="", help="Process only one run_id")
    ap.add_argument("--also-csv", action="store_true")
    args = ap.parse_args()

    work_root = Path(args.work_root)
    targets_path = work_root / "phaseB" / "derived" / "b2" / "_staging" / "b2_1_targets.parquet"
    if not targets_path.exists():
        raise SystemExit(f"[NG] targets not found: {targets_path}")

    targets = pd.read_parquet(targets_path)
    if args.run_id:
        targets = targets[targets["run_id"] == args.run_id].copy()

    if len(targets) == 0:
        print("[WARN] no targets")
        return 0

    out_runs = work_root / "phaseB" / "derived" / "b2" / "runs"
    out_staging = work_root / "phaseB" / "derived" / "b2" / "_staging"
    out_staging.mkdir(parents=True, exist_ok=True)

    all_rows: List[Dict[str, Any]] = []

    for _, t in targets.iterrows():
        run_id = str(t["run_id"])
        run_dir = out_runs / run_id
        if not run_dir.exists():
            print(f"[NG] {run_id}: missing b2 run dir: {run_dir}")
            continue

        # Inputs from B2_2a
        p_temp = run_dir / "unified_temp.parquet"
        p_gps = run_dir / "unified_gps.parquet"
        p_hr = run_dir / "unified_polar_hr.parquet"
        p_rr = run_dir / "unified_polar_rr.parquet"

        # Inputs from B2_2b
        p_acc = run_dir / "imu_accel.parquet"
        p_gyr = run_dir / "imu_gyro.parquet"
        p_ang = run_dir / "imu_angle.parquet"
        p_mag = run_dir / "imu_mag.parquet"
        p_audio = run_dir / "raw_audio_health.json"

        df_temp = _safe_read_parquet(p_temp)
        df_gps = _safe_read_parquet(p_gps)
        df_hr = _safe_read_parquet(p_hr)
        df_rr = _safe_read_parquet(p_rr)

        df_acc = _safe_read_parquet(p_acc)
        df_gyr = _safe_read_parquet(p_gyr)
        df_ang = _safe_read_parquet(p_ang)
        df_mag = _safe_read_parquet(p_mag)

        audio = _read_audio_health(p_audio)

        stats: Dict[str, Any] = {
            "run_id": run_id,
            "generated_at_iso_utc": datetime.now(timezone.utc).isoformat(),
            "inputs": {
                "unified_temp": str(p_temp),
                "unified_gps": str(p_gps),
                "polar_hr": str(p_hr),
                "polar_rr": str(p_rr),
                "imu_accel": str(p_acc),
                "imu_gyro": str(p_gyr),
                "imu_angle": str(p_ang),
                "imu_mag": str(p_mag),
                "audio_health": str(p_audio),
            },
            "temp": {},
            "gps": {},
            "polar": {},
            "imu": {},
            "audio": {},
        }

        # ---- TEMP ----
        if df_temp is None or len(df_temp) == 0:
            stats["temp"]["ok"] = False
            stats["temp"]["error"] = "missing_or_empty"
        else:
            stats["temp"]["ok"] = True
            stats["temp"]["rows"] = int(len(df_temp))
            # per sensor id (name)
            by_name = {}
            for nm, sub in df_temp.groupby("name"):
                by_name[str(nm)] = {
                    "t_mono": _span_stats_from_tmono(sub, "t_mono"),
                    "value": _basic_numeric_stats(sub["value"]),
                }
            stats["temp"]["by_sensor"] = by_name

        # ---- GPS ----
        if df_gps is None or len(df_gps) == 0:
            stats["gps"]["ok"] = False
            stats["gps"]["error"] = "missing_or_empty"
        else:
            stats["gps"]["ok"] = True
            stats["gps"]["rows"] = int(len(df_gps))
            by_name = {}
            for nm, sub in df_gps.groupby("name"):
                by_name[str(nm)] = {
                    "t_mono": _span_stats_from_tmono(sub, "t_mono"),
                    "value": _basic_numeric_stats(sub["value"]),
                }
            # fix rate (if fix exists)
            fix_rate = None
            if "fix" in set(df_gps["name"].astype(str)):
                fix = df_gps[df_gps["name"].astype(str) == "fix"]["value"]
                fix = pd.to_numeric(fix, errors="coerce")
                if fix.notna().sum() > 0:
                    fix_rate = float(np.mean(fix.dropna().to_numpy(dtype=float) > 0.5))
            stats["gps"]["by_field"] = by_name
            stats["gps"]["fix_rate"] = fix_rate

        # ---- POLAR ----
        polar = {}
        # HR
        if df_hr is not None and len(df_hr) > 0:
            polar["hr"] = {
                "rows": int(len(df_hr)),
                "t_mono": _span_stats_from_tmono(df_hr, "t_mono"),
                "bpm": _basic_numeric_stats(df_hr["value"]),
            }
        else:
            polar["hr"] = {"rows": 0}
        # RR + HRV
        if df_rr is not None and len(df_rr) > 0:
            rr = pd.to_numeric(df_rr["value"], errors="coerce").to_numpy(dtype=float)
            rr = rr[np.isfinite(rr)]
            rr = rr[rr > 0]
            # optionally trim extreme values (simple guard)
            rr = rr[(rr >= 200) & (rr <= 3000)]  # 0.2s..3s
            polar["rr_ms"] = {
                "rows": int(len(df_rr)),
                "t_mono": _span_stats_from_tmono(df_rr, "t_mono"),
                "rr_ms_stats": _basic_numeric_stats(pd.Series(rr)),
                "hrv": _hrv_from_rr_ms(rr),
            }
        else:
            polar["rr_ms"] = {"rows": 0}
        stats["polar"] = polar

        # ---- IMU ----
        imu = {}
        def imu_part(df: Optional[pd.DataFrame], label: str, cols: List[str]) -> Dict[str, Any]:
            if df is None or len(df) == 0:
                return {"ok": False, "rows": 0}
            outp: Dict[str, Any] = {"ok": True, "rows": int(len(df))}
            outp["t_mono_s"] = _span_stats_from_tmono(df.rename(columns={"t_mono_s":"t_mono"}), "t_mono")
            # rate estimate (median dt)
            s = pd.to_numeric(df["t_mono_s"], errors="coerce").dropna()
            if len(s) >= 10:
                dtv = np.diff(s.to_numpy(dtype=float))
                dtv = dtv[(dtv > 0) & (dtv < 1.0)]
                if dtv.size > 0:
                    outp["rate_hz_median"] = float(1.0 / np.median(dtv))
            for c in cols:
                if c in df.columns:
                    outp[c] = _basic_numeric_stats(df[c])
            return outp

        imu["accel"] = imu_part(df_acc, "accel", ["ax_g", "ay_g", "az_g", "temp_raw"])
        imu["gyro"] = imu_part(df_gyr, "gyro", ["gx_dps", "gy_dps", "gz_dps", "temp_raw"])
        imu["angle"] = imu_part(df_ang, "angle", ["roll_deg", "pitch_deg", "yaw_deg", "temp_raw"])
        imu["mag"] = imu_part(df_mag, "mag", ["mx_raw", "my_raw", "mz_raw", "temp_raw"])
        stats["imu"] = imu

        # ---- AUDIO ----
        stats["audio"] = {
            "ok": bool(audio.get("ok", False)),
            "duration_s": audio.get("duration_s", None),
            "sample_rate_hz": audio.get("sample_rate_hz", None),
            "rms_i16": audio.get("rms_i16", None),
            "clip_ratio": audio.get("clip_ratio", None),
        }

        # write per-run json
        out_json = run_dir / "b2_3_stats.json"
        out_json.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] {run_id}: wrote {out_json}")

        # flatten for cross-run table (minimum useful fields)
        row = {
            "run_id": run_id,
            "temp_rows": None if df_temp is None else int(len(df_temp)),
            "gps_rows": None if df_gps is None else int(len(df_gps)),
            "polar_hr_rows": None if df_hr is None else int(len(df_hr)),
            "polar_rr_rows": None if df_rr is None else int(len(df_rr)),
            "imu_accel_rows": None if df_acc is None else int(len(df_acc)),
            "imu_gyro_rows": None if df_gyr is None else int(len(df_gyr)),
            "imu_angle_rows": None if df_ang is None else int(len(df_ang)),
            "imu_mag_rows": None if df_mag is None else int(len(df_mag)),
            "gps_fix_rate": stats["gps"].get("fix_rate", None),
            "audio_ok": stats["audio"]["ok"],
            "audio_duration_s": stats["audio"]["duration_s"],
            "generated_at_iso_utc": stats["generated_at_iso_utc"],
        }
        all_rows.append(row)

    # cross-run parquet/csv
    all_df = pd.DataFrame(all_rows)
    out_pq = out_staging / "b2_3_sensor_stats_all.parquet"
    all_df.to_parquet(out_pq, index=False)

    if args.also_csv:
        out_csv = out_staging / "b2_3_sensor_stats_all.csv"
        all_df.to_csv(out_csv, index=False, encoding="utf-8-sig")

    print(f"[OK] wrote: {out_pq}")
    if args.also_csv:
        print(f"[OK] wrote: {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
