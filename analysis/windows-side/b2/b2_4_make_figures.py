#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase B2-4: Basic visualization per run (PNG figures)

Inputs:
  work/phaseB/derived/b2/_staging/b2_1_targets.parquet
  work/phaseB/derived/b2/runs/<run_id>/unified_*.parquet
  work/phaseB/derived/b2/runs/<run_id>/imu_*.parquet

Outputs:
  work/phaseB/figures/b2/runs/<run_id>/*.png

Run:
  conda activate phaseb
  python b2_4_make_figures.py
  python b2_4_make_figures.py --max-points 20000
  python b2_4_make_figures.py --run-id run_....
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


def _read_parquet(p: Path) -> Optional[pd.DataFrame]:
    return pd.read_parquet(p) if p.exists() else None


def _rel_time_from_tmono(df: pd.DataFrame, col: str) -> np.ndarray:
    t = pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=float)
    t = t[np.isfinite(t)]
    if t.size == 0:
        return np.array([], dtype=float)
    t0 = t[0]
    return t - t0


def _downsample_df(df: pd.DataFrame, max_points: int) -> pd.DataFrame:
    if df is None or len(df) <= max_points:
        return df
    step = int(np.ceil(len(df) / max_points))
    return df.iloc[::step].copy()


def _save(fig, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_temp(df_temp: pd.DataFrame, out_dir: Path) -> None:
    if df_temp is None or len(df_temp) == 0:
        return

    # t_mono is in unified_* (seconds, monotonic)
    df_temp = df_temp.copy()
    df_temp["t_rel_s"] = df_temp["t_mono"] - pd.to_numeric(df_temp["t_mono"], errors="coerce").iloc[0]
    df_temp["value"] = pd.to_numeric(df_temp["value"], errors="coerce")

    fig = plt.figure()
    ax = fig.add_subplot(1, 1, 1)
    for nm, sub in df_temp.groupby("name"):
        ax.plot(sub["t_rel_s"], sub["value"], label=str(nm))
    ax.set_title("Temperature (temp) vs time")
    ax.set_xlabel("t_rel (s)")
    ax.set_ylabel("value (degC or raw unit)")
    ax.legend()
    _save(fig, out_dir / "temp_timeseries.png")


def plot_gps(df_gps: pd.DataFrame, out_dir: Path) -> None:
    if df_gps is None or len(df_gps) == 0:
        return

    df = df_gps.copy()
    df["t_rel_s"] = df["t_mono"] - pd.to_numeric(df["t_mono"], errors="coerce").iloc[0]
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    # speed + fix
    sp = df[df["name"].astype(str) == "speed_mps"].copy()
    fx = df[df["name"].astype(str) == "fix"].copy()

    if len(sp) > 0 or len(fx) > 0:
        fig = plt.figure()
        ax = fig.add_subplot(1, 1, 1)
        if len(sp) > 0:
            ax.plot(sp["t_rel_s"], sp["value"] * 3.6)  # km/h
        ax.set_title("GPS speed (km/h) and fix")
        ax.set_xlabel("t_rel (s)")
        ax.set_ylabel("speed (km/h)")

        if len(fx) > 0:
            ax2 = ax.twinx()
            ax2.plot(fx["t_rel_s"], fx["value"])
            ax2.set_ylabel("fix (0/1)")
        _save(fig, out_dir / "gps_speed_fix.png")

    # track (lat/lon)
    la = df[df["name"].astype(str) == "lat"].copy()
    lo = df[df["name"].astype(str) == "lon"].copy()

    # If lat/lon lengths differ, align by nearest t_mono via merge_asof
    if len(la) > 0 and len(lo) > 0:
        la2 = la[["t_mono", "value"]].rename(columns={"value": "lat"}).sort_values("t_mono")
        lo2 = lo[["t_mono", "value"]].rename(columns={"value": "lon"}).sort_values("t_mono")
        track = pd.merge_asof(la2, lo2, on="t_mono", direction="nearest", tolerance=1.0)
        track = track.dropna()

        if len(track) > 2:
            fig = plt.figure()
            ax = fig.add_subplot(1, 1, 1)
            ax.plot(track["lon"], track["lat"])
            ax.set_title("GPS track (lon vs lat)")
            ax.set_xlabel("lon")
            ax.set_ylabel("lat")
            _save(fig, out_dir / "gps_track.png")


def plot_polar(df_hr: pd.DataFrame, df_rr: pd.DataFrame, out_dir: Path) -> None:
    # HR timeseries
    if df_hr is not None and len(df_hr) > 0:
        df = df_hr.copy()
        df["t_rel_s"] = df["t_mono"] - pd.to_numeric(df["t_mono"], errors="coerce").iloc[0]
        df["value"] = pd.to_numeric(df["value"], errors="coerce")

        fig = plt.figure()
        ax = fig.add_subplot(1, 1, 1)
        ax.plot(df["t_rel_s"], df["value"])
        ax.set_title("Polar HR (bpm) vs time")
        ax.set_xlabel("t_rel (s)")
        ax.set_ylabel("HR (bpm)")
        _save(fig, out_dir / "polar_hr.png")

    # RR histogram
    if df_rr is not None and len(df_rr) > 0:
        rr = pd.to_numeric(df_rr["value"], errors="coerce").to_numpy(dtype=float)
        rr = rr[np.isfinite(rr)]
        rr = rr[(rr >= 200) & (rr <= 3000)]  # guard
        if rr.size > 0:
            fig = plt.figure()
            ax = fig.add_subplot(1, 1, 1)
            ax.hist(rr, bins=60)
            ax.set_title("Polar RR interval histogram")
            ax.set_xlabel("RR (ms)")
            ax.set_ylabel("count")
            _save(fig, out_dir / "polar_rr_hist.png")


def _plot_imu_xyz(df: pd.DataFrame, tcol: str, cols: Tuple[str, str, str], title: str, ylab: str, out_path: Path, max_points: int) -> None:
    if df is None or len(df) == 0:
        return
    df = df.copy()
    df = df.sort_values(tcol)
    df = _downsample_df(df, max_points=max_points)

    t = pd.to_numeric(df[tcol], errors="coerce")
    if t.notna().sum() == 0:
        return
    t_rel = (t - t.iloc[0]).to_numpy(dtype=float)

    fig = plt.figure()
    ax = fig.add_subplot(1, 1, 1)
    for c in cols:
        if c in df.columns:
            ax.plot(t_rel, pd.to_numeric(df[c], errors="coerce"), label=c)
    ax.set_title(title)
    ax.set_xlabel("t_rel (s)")
    ax.set_ylabel(ylab)
    ax.legend()
    _save(fig, out_path)


def plot_imu(df_acc: pd.DataFrame, df_gyr: pd.DataFrame, df_ang: pd.DataFrame, out_dir: Path, max_points: int) -> None:
    _plot_imu_xyz(
        df_acc, "t_mono_s",
        ("ax_g", "ay_g", "az_g"),
        "IMU accel (g) vs time",
        "accel (g)",
        out_dir / "imu_accel.png",
        max_points=max_points,
    )
    _plot_imu_xyz(
        df_gyr, "t_mono_s",
        ("gx_dps", "gy_dps", "gz_dps"),
        "IMU gyro (dps) vs time",
        "gyro (deg/s)",
        out_dir / "imu_gyro.png",
        max_points=max_points,
    )
    _plot_imu_xyz(
        df_ang, "t_mono_s",
        ("roll_deg", "pitch_deg", "yaw_deg"),
        "IMU angle (deg) vs time",
        "angle (deg)",
        out_dir / "imu_angle.png",
        max_points=max_points,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-root", default=r"D:\701lab\work")
    ap.add_argument("--run-id", default="", help="Process only one run_id")
    ap.add_argument("--max-points", type=int, default=30000, help="Max points per IMU plot (downsample)")
    ap.add_argument("--no-imu", action="store_true", help="Skip IMU plots")
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

    derived_runs = work_root / "phaseB" / "derived" / "b2" / "runs"
    fig_root = work_root / "phaseB" / "figures" / "b2" / "runs"
    fig_root.mkdir(parents=True, exist_ok=True)

    for _, t in targets.iterrows():
        run_id = str(t["run_id"])
        run_dir = derived_runs / run_id
        if not run_dir.exists():
            print(f"[NG] {run_id}: missing derived dir: {run_dir}")
            continue

        out_dir = fig_root / run_id
        out_dir.mkdir(parents=True, exist_ok=True)

        # unified
        df_temp = _read_parquet(run_dir / "unified_temp.parquet")
        df_gps = _read_parquet(run_dir / "unified_gps.parquet")
        df_hr = _read_parquet(run_dir / "unified_polar_hr.parquet")
        df_rr = _read_parquet(run_dir / "unified_polar_rr.parquet")

        plot_temp(df_temp, out_dir)
        plot_gps(df_gps, out_dir)
        plot_polar(df_hr, df_rr, out_dir)

        if not args.no_imu:
            df_acc = _read_parquet(run_dir / "imu_accel.parquet")
            df_gyr = _read_parquet(run_dir / "imu_gyro.parquet")
            df_ang = _read_parquet(run_dir / "imu_angle.parquet")
            plot_imu(df_acc, df_gyr, df_ang, out_dir, max_points=args.max_points)

        print(f"[OK] {run_id}: wrote figures -> {out_dir}")

    print(f"[OK] figures root: {fig_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
