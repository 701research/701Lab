#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase B2-5: Sensor quality metrics (run x sensor)

Purpose
- Quantify "signal health" deeper than B1 QC.
- Provide numeric gates so B3 (segment/event extraction) can rely on runs.

Inputs (produced by B2_1..B2_2a..B2_2b):
  work/phaseB/derived/b2/_staging/b2_1_targets.parquet
  work/phaseB/derived/b2/runs/<run_id>/unified_*.parquet
  work/phaseB/derived/b2/runs/<run_id>/imu_*.parquet
  work/phaseB/derived/b2/runs/<run_id>/raw_audio_health.json

Outputs:
  work/phaseB/derived/b2/b2_5_sensor_quality.parquet
  (optional) ...csv

Run:
  conda activate phaseb
  python b2_5_sensor_quality.py --also-csv
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd


def _read_pq(p: Path) -> Optional[pd.DataFrame]:
    return pd.read_parquet(p) if p.exists() else None


def _audio_health(p: Path) -> Dict[str, Any]:
    if not p.exists():
        return {"ok": False, "error": "missing", "path": str(p)}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {"ok": False, "error": f"json_error:{e}", "path": str(p)}


def _within_rate(rate: Optional[float], lo: float, hi: float) -> Optional[bool]:
    if rate is None:
        return None
    return (lo <= rate <= hi)


def _tmono_span_and_rate(
    df: Optional[pd.DataFrame],
    tcol: str,
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float], Optional[float]]:
    """
    Returns (first, last, span_s, rate_hz_mean, rate_hz_median_dt)

    Notes
    - rate_hz_mean = (n-1)/span  (robust even if many near-duplicate timestamps exist)
    - rate_hz_median_dt = 1/median(dt) (diagnostic; can be misleading for multi-sensor interleaved logs)
    """
    if df is None or len(df) == 0 or tcol not in df.columns:
        return (None, None, None, None, None)

    t = pd.to_numeric(df[tcol], errors="coerce").dropna()
    if len(t) < 2:
        if len(t) == 1:
            v = float(t.iloc[0])
            return (v, v, 0.0, None, None)
        return (None, None, None, None, None)

    # IMPORTANT: sort by time
    t = t.sort_values(kind="mergesort").reset_index(drop=True)

    first = float(t.iloc[0])
    last = float(t.iloc[-1])
    span = float(last - first)

    rate_mean = None
    if span > 0:
        rate_mean = float((len(t) - 1) / span)

    dt = np.diff(t.to_numpy(dtype=float))
    dt = dt[(dt > 0) & (dt < 10.0)]
    rate_med = float(1.0 / np.median(dt)) if dt.size > 0 else None

    return (first, last, span, rate_mean, rate_med)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-root", default=r"D:\701lab\work")
    ap.add_argument("--also-csv", action="store_true")
    ap.add_argument("--run-id", default="", help="Process only one run_id")
    args = ap.parse_args()

    work_root = Path(args.work_root)
    targets_path = work_root / "phaseB" / "derived" / "b2" / "_staging" / "b2_1_targets.parquet"
    if not targets_path.exists():
        raise SystemExit(f"[NG] targets not found: {targets_path}")

    targets = pd.read_parquet(targets_path)
    if args.run_id:
        targets = targets[targets["run_id"] == args.run_id].copy()

    derived_runs = work_root / "phaseB" / "derived" / "b2" / "runs"
    out_dir = work_root / "phaseB" / "derived" / "b2"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []

    for _, t in targets.iterrows():
        run_id = str(t["run_id"])
        rd = derived_runs / run_id
        if not rd.exists():
            print(f"[NG] {run_id}: missing derived dir: {rd}")
            continue

        # ---------- TEMP ----------
        df_temp = _read_pq(rd / "unified_temp.parquet")
        temp_rows = int(len(df_temp)) if df_temp is not None else 0
        _, _, temp_span, temp_rate_mean, temp_rate_med = _tmono_span_and_rate(df_temp, "t_mono")
        # expected: ~0.5-2Hz (loose gate). Use MEAN rate for gating.
        temp_rate_ok = _within_rate(temp_rate_mean, 0.2, 5.0)
        temp_ok = (temp_rows > 10) and (temp_span is not None and temp_span > 30) and (temp_rate_ok is not False)

        # if 2 sensors present, check delta stability (median |T1-T2|)
        temp_delta_med = None
        if df_temp is not None and len(df_temp) > 0 and "name" in df_temp.columns:
            names = sorted(set(df_temp["name"].astype(str)))
            if len(names) >= 2:
                a = (
                    df_temp[df_temp["name"].astype(str) == names[0]][["t_mono", "value"]]
                    .rename(columns={"value": "v0"})
                    .sort_values("t_mono")
                )
                b = (
                    df_temp[df_temp["name"].astype(str) == names[1]][["t_mono", "value"]]
                    .rename(columns={"value": "v1"})
                    .sort_values("t_mono")
                )
                m = pd.merge_asof(a, b, on="t_mono", direction="nearest", tolerance=5.0).dropna()
                if len(m) > 50:
                    dv = (pd.to_numeric(m["v0"], errors="coerce") - pd.to_numeric(m["v1"], errors="coerce")).dropna()
                    if len(dv) > 0:
                        temp_delta_med = float(np.median(np.abs(dv)))

        # ---------- GPS ----------
        df_gps = _read_pq(rd / "unified_gps.parquet")
        gps_rows = int(len(df_gps)) if df_gps is not None else 0
        _, _, gps_span, gps_rate_mean, gps_rate_med = _tmono_span_and_rate(df_gps, "t_mono")

        gps_fix_rate = None
        gps_speed_bad_rate = None
        gps_drift_when_stop = None

        if df_gps is not None and len(df_gps) > 0:
            df_gps2 = df_gps.copy()
            df_gps2["name"] = df_gps2["name"].astype(str)
            df_gps2["value"] = pd.to_numeric(df_gps2["value"], errors="coerce")

            fx = df_gps2[df_gps2["name"] == "fix"]["value"].dropna()
            if len(fx) > 0:
                gps_fix_rate = float(np.mean(fx.to_numpy(dtype=float) > 0.5))

            sp = df_gps2[df_gps2["name"] == "speed_mps"][["t_mono", "value"]].dropna()
            if len(sp) > 0:
                v = sp["value"].to_numpy(dtype=float)
                # invalid: negative or too large ( > 100 m/s = 360 km/h)
                gps_speed_bad_rate = float(np.mean((v < -0.5) | (v > 100.0)))

            # drift while stopped: when speed < 0.5m/s, check lat/lon movement (rough proxy)
            la = df_gps2[df_gps2["name"] == "lat"][["t_mono", "value"]].dropna().rename(columns={"value": "lat"}).sort_values("t_mono")
            lo = df_gps2[df_gps2["name"] == "lon"][["t_mono", "value"]].dropna().rename(columns={"value": "lon"}).sort_values("t_mono")
            if len(la) > 50 and len(lo) > 50 and len(sp) > 50:
                track = pd.merge_asof(la, lo, on="t_mono", direction="nearest", tolerance=2.0)
                track = pd.merge_asof(track.sort_values("t_mono"), sp.sort_values("t_mono"), on="t_mono", direction="nearest", tolerance=2.0)
                track = track.dropna()
                if len(track) > 50:
                    stop = track[track["value"] < 0.5].copy()  # speed_mps in "value"
                    if len(stop) > 10:
                        dlat = np.diff(stop["lat"].to_numpy(dtype=float))
                        dlon = np.diff(stop["lon"].to_numpy(dtype=float))
                        dist = np.sqrt(dlat * dlat + dlon * dlon)
                        gps_drift_when_stop = float(np.median(dist)) if dist.size > 0 else None

        # loose gates
        gps_ok = (
            (gps_rows > 10)
            and (gps_fix_rate is None or gps_fix_rate > 0.7)
            and (gps_speed_bad_rate is None or gps_speed_bad_rate < 0.01)
        )

        # ---------- POLAR ----------
        df_hr = _read_pq(rd / "unified_polar_hr.parquet")
        df_rr = _read_pq(rd / "unified_polar_rr.parquet")
        hr_rows = int(len(df_hr)) if df_hr is not None else 0
        rr_rows = int(len(df_rr)) if df_rr is not None else 0

        _, _, hr_span, hr_rate_mean, hr_rate_med = _tmono_span_and_rate(df_hr, "t_mono")
        _, _, rr_span, rr_rate_mean, rr_rate_med = _tmono_span_and_rate(df_rr, "t_mono")

        hr_bad_rate = None
        rr_bad_rate = None
        if df_hr is not None and len(df_hr) > 0:
            v = pd.to_numeric(df_hr["value"], errors="coerce").dropna().to_numpy(dtype=float)
            if v.size > 0:
                hr_bad_rate = float(np.mean((v < 30) | (v > 240)))
        if df_rr is not None and len(df_rr) > 0:
            v = pd.to_numeric(df_rr["value"], errors="coerce").dropna().to_numpy(dtype=float)
            if v.size > 0:
                rr_bad_rate = float(np.mean((v < 200) | (v > 3000)))

        polar_ok = (
            (hr_rows > 10)
            and (rr_rows > 10)
            and (hr_bad_rate is None or hr_bad_rate < 0.02)
            and (rr_bad_rate is None or rr_bad_rate < 0.05)
        )

        # ---------- IMU ----------
        df_acc = _read_pq(rd / "imu_accel.parquet")
        df_gyr = _read_pq(rd / "imu_gyro.parquet")
        df_ang = _read_pq(rd / "imu_angle.parquet")
        df_mag = _read_pq(rd / "imu_mag.parquet")

        acc_rows = int(len(df_acc)) if df_acc is not None else 0
        gyr_rows = int(len(df_gyr)) if df_gyr is not None else 0
        ang_rows = int(len(df_ang)) if df_ang is not None else 0
        mag_rows = int(len(df_mag)) if df_mag is not None else 0

        _, _, acc_span, acc_rate_mean, acc_rate_med = _tmono_span_and_rate(df_acc, "t_mono_s")
        _, _, gyr_span, gyr_rate_mean, gyr_rate_med = _tmono_span_and_rate(df_gyr, "t_mono_s")
        _, _, ang_span, ang_rate_mean, ang_rate_med = _tmono_span_and_rate(df_ang, "t_mono_s")

        # gate based on MEAN rate (robust)
        imu_rate_ok = _within_rate(acc_rate_mean, 3.0, 50.0)

        # frame balance: each within 20% of median
        frame_counts = np.array([acc_rows, gyr_rows, ang_rows, mag_rows], dtype=float)
        frame_balance_ok = None
        if np.all(frame_counts > 0):
            med = float(np.median(frame_counts))
            frame_balance_ok = bool(np.all(np.abs(frame_counts - med) / med < 0.2)) if med > 0 else None

        # abnormal value rates (very loose guards)
        acc_bad = None
        gyr_bad = None

        if df_acc is not None and len(df_acc) > 0:
            ax = pd.to_numeric(df_acc.get("ax_g", pd.Series([], dtype=float)), errors="coerce").dropna().to_numpy(dtype=float)
            ay = pd.to_numeric(df_acc.get("ay_g", pd.Series([], dtype=float)), errors="coerce").dropna().to_numpy(dtype=float)
            az = pd.to_numeric(df_acc.get("az_g", pd.Series([], dtype=float)), errors="coerce").dropna().to_numpy(dtype=float)
            if ax.size > 0 and ay.size > 0 and az.size > 0:
                n = min(ax.size, ay.size, az.size)
                aabs = np.sqrt(ax[:n] * ax[:n] + ay[:n] * ay[:n] + az[:n] * az[:n])
                acc_bad = float(np.mean((aabs > 8.0) | (aabs < 0.2)))  # >8g or almost zero

        if df_gyr is not None and len(df_gyr) > 0:
            gx = pd.to_numeric(df_gyr.get("gx_dps", pd.Series([], dtype=float)), errors="coerce").dropna().to_numpy(dtype=float)
            gy = pd.to_numeric(df_gyr.get("gy_dps", pd.Series([], dtype=float)), errors="coerce").dropna().to_numpy(dtype=float)
            gz = pd.to_numeric(df_gyr.get("gz_dps", pd.Series([], dtype=float)), errors="coerce").dropna().to_numpy(dtype=float)
            if gx.size > 0 and gy.size > 0 and gz.size > 0:
                n = min(gx.size, gy.size, gz.size)
                gabs = np.sqrt(gx[:n] * gx[:n] + gy[:n] * gy[:n] + gz[:n] * gz[:n])
                gyr_bad = float(np.mean(gabs > 1500.0))

        imu_ok = (
            (acc_rows > 1000)
            and (gyr_rows > 1000)
            and (ang_rows > 1000)
            and (imu_rate_ok is not False)
            and (frame_balance_ok is not False)
            and (acc_bad is None or acc_bad < 0.01)
            and (gyr_bad is None or gyr_bad < 0.01)
        )

        # ---------- AUDIO (health only) ----------
        audio = _audio_health(rd / "raw_audio_health.json")
        audio_ok = bool(audio.get("ok", False))
        audio_clip = audio.get("clip_ratio", None)

        sensor_ok_flag = bool(temp_ok and gps_ok and polar_ok and imu_ok)

        rows.append({
            "run_id": run_id,
            "generated_at_iso_utc": datetime.now(timezone.utc).isoformat(),

            "temp_rows": temp_rows,
            "temp_span_s": temp_span,
            "temp_rate_hz_mean": temp_rate_mean,
            "temp_rate_hz_median_dt": temp_rate_med,
            "temp_delta_median_abs": temp_delta_med,
            "temp_ok": temp_ok,

            "gps_rows": gps_rows,
            "gps_span_s": gps_span,
            "gps_rate_hz_mean": gps_rate_mean,
            "gps_rate_hz_median_dt": gps_rate_med,
            "gps_fix_rate": gps_fix_rate,
            "gps_speed_bad_rate": gps_speed_bad_rate,
            "gps_drift_stop_median_step_deg": gps_drift_when_stop,
            "gps_ok": gps_ok,

            "polar_hr_rows": hr_rows,
            "polar_hr_span_s": hr_span,
            "polar_hr_rate_hz_mean": hr_rate_mean,
            "polar_hr_rate_hz_median_dt": hr_rate_med,
            "polar_hr_bad_rate": hr_bad_rate,

            "polar_rr_rows": rr_rows,
            "polar_rr_span_s": rr_span,
            "polar_rr_rate_hz_mean": rr_rate_mean,
            "polar_rr_rate_hz_median_dt": rr_rate_med,
            "polar_rr_bad_rate": rr_bad_rate,
            "polar_ok": polar_ok,

            "imu_accel_rows": acc_rows,
            "imu_gyro_rows": gyr_rows,
            "imu_angle_rows": ang_rows,
            "imu_mag_rows": mag_rows,
            "imu_span_s": acc_span,
            "imu_rate_hz_mean": acc_rate_mean,
            "imu_rate_hz_median_dt": acc_rate_med,
            "imu_frame_balance_ok": frame_balance_ok,
            "imu_acc_bad_rate": acc_bad,
            "imu_gyro_bad_rate": gyr_bad,
            "imu_ok": imu_ok,

            "audio_ok": audio_ok,
            "audio_clip_ratio": audio_clip,

            "sensor_ok_flag": sensor_ok_flag,
        })

        print(
            f"[OK] {run_id}: "
            f"temp_ok={temp_ok} gps_ok={gps_ok} polar_ok={polar_ok} imu_ok={imu_ok} "
            f"-> sensor_ok_flag={sensor_ok_flag}"
        )

    df_out = pd.DataFrame(rows)
    out_pq = out_dir / "b2_5_sensor_quality.parquet"
    df_out.to_parquet(out_pq, index=False)

    if args.also_csv:
        out_csv = out_dir / "b2_5_sensor_quality.csv"
        df_out.to_csv(out_csv, index=False, encoding="utf-8-sig")

    print(f"[OK] wrote: {out_pq}")
    if args.also_csv:
        print(f"[OK] wrote: {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
