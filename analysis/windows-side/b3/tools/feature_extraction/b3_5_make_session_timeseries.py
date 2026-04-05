#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, Dict, List, Tuple

import numpy as np
import pandas as pd


# ------------------------------------------------------------
# Utility
# ------------------------------------------------------------

SESSION_NAME_MAP = {
    "SS": "no_music_start",
    "S1": "intro",
    "S2": "propulsion",
    "S3": "peak1",
    "S4": "bridge",
    "S5": "peak2",
    "S6": "landing",
    "SE": "no_music_end",
}


def read_parquet_if_exists(path: Path) -> Optional[pd.DataFrame]:
    return pd.read_parquet(path) if path.exists() else None


def read_csv_if_exists(path: Path) -> Optional[pd.DataFrame]:
    return pd.read_csv(path) if path.exists() else None


def rolling_mean(series: pd.Series, window: int) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    return s.rolling(window=window, center=True, min_periods=1).mean()


def parse_hms_to_seconds(hms: str) -> int:
    parts = str(hms).strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid HH:MM:SS string: {hms}")
    hh, mm, ss = map(int, parts)
    return hh * 3600 + mm * 60 + ss


def _parse_iso_hms_to_seconds(series: pd.Series) -> pd.Series:
    dt = pd.to_datetime(series, errors="coerce")
    out = pd.Series(np.nan, index=series.index, dtype=float)
    mask = dt.notna()
    out.loc[mask] = (
        dt.loc[mask].dt.hour.astype(float) * 3600.0
        + dt.loc[mask].dt.minute.astype(float) * 60.0
        + dt.loc[mask].dt.second.astype(float)
        + dt.loc[mask].dt.microsecond.astype(float) / 1_000_000.0
    )
    return out


def safe_interp_series(
    x_src: np.ndarray,
    y_src: np.ndarray,
    x_dst: np.ndarray,
) -> np.ndarray:
    """
    Linear interpolation with NaN outside valid range.
    """
    out = np.full(len(x_dst), np.nan, dtype=float)
    mask = np.isfinite(x_src) & np.isfinite(y_src)
    x = x_src[mask]
    y = y_src[mask]
    if len(x) < 2:
        return out

    order = np.argsort(x)
    x = x[order]
    y = y[order]

    # drop duplicated x by averaging
    df = pd.DataFrame({"x": x, "y": y}).groupby("x", as_index=False)["y"].mean()
    x = df["x"].to_numpy(dtype=float)
    y = df["y"].to_numpy(dtype=float)

    if len(x) < 2:
        return out

    inside = (x_dst >= x[0]) & (x_dst <= x[-1]) & np.isfinite(x_dst)
    out[inside] = np.interp(x_dst[inside], x, y)
    return out


def clip_by_abs_time(df: Optional[pd.DataFrame], tcol: str, t_start: float, t_end: float) -> Optional[pd.DataFrame]:
    if df is None or len(df) == 0 or tcol not in df.columns:
        return df
    t = pd.to_numeric(df[tcol], errors="coerce")
    mask = t.notna() & (t >= float(t_start)) & (t <= float(t_end))
    return df.loc[mask].copy()


def clip_by_rel_time(df: Optional[pd.DataFrame], tcol: str, t_start: float, t_end: float) -> Optional[pd.DataFrame]:
    if df is None or len(df) == 0 or tcol not in df.columns:
        return df

    out = df.copy()
    t = pd.to_numeric(out[tcol], errors="coerce")
    valid = t.dropna()
    if len(valid) == 0:
        return out.iloc[0:0].copy()

    t0 = float(valid.iloc[0])
    t_rel = t - t0

    mask = t_rel.notna() & (t_rel >= float(t_start)) & (t_rel <= float(t_end))
    return out.loc[mask].copy()


# ------------------------------------------------------------
# Session table
# ------------------------------------------------------------

def read_session_excel(path: Path) -> Tuple[str, pd.DataFrame]:
    raw = pd.read_excel(path, header=None)
    run_id = str(raw.iloc[0, 1]).strip()
    header = raw.iloc[1].tolist()
    df = raw.iloc[2:].copy()
    df.columns = header
    df = df.rename(columns={
        "GPS_time": "session_id",
        "start": "gps_start_time",
        "end": "gps_end_time",
    })
    df["run_id"] = run_id
    df["session_name"] = df["session_id"].map(SESSION_NAME_MAP).fillna(df["session_id"])
    df["gps_start_sec"] = df["gps_start_time"].apply(parse_hms_to_seconds)
    df["gps_end_sec"] = df["gps_end_time"].apply(parse_hms_to_seconds)
    df["duration_sec"] = df["gps_end_sec"] - df["gps_start_sec"]
    return run_id, df


# ------------------------------------------------------------
# Time axis mapping via unified_gps.csv
# ------------------------------------------------------------

def build_clock_to_mono_map(df_gps_unified: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df_gps_unified is None or len(df_gps_unified) == 0:
        return None
    if not {"t_mono", "t_wall"}.issubset(df_gps_unified.columns):
        return None

    base = df_gps_unified.copy()
    base["t_mono_num"] = pd.to_numeric(base["t_mono"], errors="coerce")
    base["clock_sec"] = _parse_iso_hms_to_seconds(base["t_wall"])

    clock_map = (
        base.dropna(subset=["clock_sec", "t_mono_num"])
        .groupby("clock_sec", as_index=False)["t_mono_num"]
        .mean()
        .sort_values("clock_sec")
        .rename(columns={"t_mono_num": "t_mono"})
    )

    if len(clock_map) < 2:
        return None
    return clock_map


def _interpolate_clock_to_mono(clock_map: pd.DataFrame, clock_sec: pd.Series) -> pd.Series:
    if clock_map is None or len(clock_map) < 2:
        return pd.Series(np.nan, index=clock_sec.index, dtype=float)

    xp = pd.to_numeric(clock_map["clock_sec"], errors="coerce").to_numpy(dtype=float)
    fp = pd.to_numeric(clock_map["t_mono"], errors="coerce").to_numpy(dtype=float)
    mask = np.isfinite(xp) & np.isfinite(fp)
    xp = xp[mask]
    fp = fp[mask]
    if len(xp) < 2:
        return pd.Series(np.nan, index=clock_sec.index, dtype=float)

    order = np.argsort(xp)
    xp = xp[order]
    fp = fp[order]

    x = pd.to_numeric(clock_sec, errors="coerce").to_numpy(dtype=float)
    out = np.full_like(x, np.nan, dtype=float)
    valid = np.isfinite(x)
    if np.any(valid):
        out[valid] = np.interp(x[valid], xp, fp, left=np.nan, right=np.nan)
        out[valid & (x < xp[0])] = np.nan
        out[valid & (x > xp[-1])] = np.nan

    return pd.Series(out, index=clock_sec.index, dtype=float)


def map_sessions_to_mono(
    session_df: pd.DataFrame,
    df_gps_unified: Optional[pd.DataFrame],
    run_start_gps_time: Optional[str],
) -> Tuple[pd.DataFrame, str]:
    out = session_df.copy()
    clock_map = build_clock_to_mono_map(df_gps_unified)

    if clock_map is not None:
        out["t_start_sec"] = _interpolate_clock_to_mono(clock_map, out["gps_start_sec"])
        out["t_end_sec"] = _interpolate_clock_to_mono(clock_map, out["gps_end_sec"])
        mode = "unified_gps_csv_t_wall_to_t_mono"
        return out, mode

    if run_start_gps_time:
        run_start_gps_sec = parse_hms_to_seconds(run_start_gps_time)
        out["t_start_sec"] = out["gps_start_sec"] - run_start_gps_sec
        out["t_end_sec"] = out["gps_end_sec"] - run_start_gps_sec
        mode = "fallback_relative_from_run_start_gps_time"
        return out, mode

    fallback = int(out["gps_start_sec"].min())
    out["t_start_sec"] = out["gps_start_sec"] - fallback
    out["t_end_sec"] = out["gps_end_sec"] - fallback
    mode = "fallback_relative_from_first_session_start"
    return out, mode


# ------------------------------------------------------------
# Per-modality preprocessing
# ------------------------------------------------------------

def prep_gps(df_gps: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df_gps is None or len(df_gps) == 0:
        return None
    if not {"t_mono", "name", "value"}.issubset(df_gps.columns):
        return None

    sp = df_gps[df_gps["name"].astype(str) == "speed_mps"].copy()
    if len(sp) == 0:
        return None

    out = pd.DataFrame({
        "t": pd.to_numeric(sp["t_mono"], errors="coerce"),
        "speed_kmh": pd.to_numeric(sp["value"], errors="coerce") * 3.6,
    }).dropna(subset=["t"])
    return out.sort_values("t").reset_index(drop=True)


def prep_hr(df_hr: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df_hr is None or len(df_hr) == 0 or not {"t_mono", "value"}.issubset(df_hr.columns):
        return None

    out = pd.DataFrame({
        "t": pd.to_numeric(df_hr["t_mono"], errors="coerce"),
        "hr_bpm": pd.to_numeric(df_hr["value"], errors="coerce"),
    }).dropna(subset=["t"])
    return out.sort_values("t").reset_index(drop=True)


def prep_rr(df_rr: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df_rr is None or len(df_rr) == 0 or not {"t_mono", "value"}.issubset(df_rr.columns):
        return None

    rr = pd.to_numeric(df_rr["value"], errors="coerce")
    rr = rr.where((rr >= 200) & (rr <= 3000), np.nan)

    out = pd.DataFrame({
        "t": pd.to_numeric(df_rr["t_mono"], errors="coerce"),
        "rr_ms": rr,
    }).dropna(subset=["t"])
    return out.sort_values("t").reset_index(drop=True)


def prep_acc(df_acc: Optional[pd.DataFrame], smooth_window: int) -> Optional[pd.DataFrame]:
    if df_acc is None or len(df_acc) == 0 or "t_mono_s" not in df_acc.columns:
        return None

    out = df_acc.copy()
    out["t"] = pd.to_numeric(out["t_mono_s"], errors="coerce")

    for c in ["ax_g", "ay_g", "az_g"]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
            out[f"{c}_s"] = rolling_mean(out[c], smooth_window)

    keep = ["t"]
    for c in ["ax_g", "ay_g", "az_g", "ax_g_s", "ay_g_s", "az_g_s"]:
        if c in out.columns:
            keep.append(c)

    out = out[keep].dropna(subset=["t"]).sort_values("t").reset_index(drop=True)
    return out


def prep_gyr(df_gyr: Optional[pd.DataFrame], smooth_window: int) -> Optional[pd.DataFrame]:
    if df_gyr is None or len(df_gyr) == 0 or "t_mono_s" not in df_gyr.columns:
        return None

    out = df_gyr.copy()
    out["t"] = pd.to_numeric(out["t_mono_s"], errors="coerce")

    for c in ["gx_dps", "gy_dps", "gz_dps"]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
            out[f"{c}_s"] = rolling_mean(out[c], smooth_window)

    keep = ["t"]
    for c in ["gx_dps", "gy_dps", "gz_dps", "gx_dps_s", "gy_dps_s", "gz_dps_s"]:
        if c in out.columns:
            keep.append(c)

    out = out[keep].dropna(subset=["t"]).sort_values("t").reset_index(drop=True)
    return out


def prep_ang(df_ang: Optional[pd.DataFrame], smooth_window: int) -> Optional[pd.DataFrame]:
    if df_ang is None or len(df_ang) == 0 or "t_mono_s" not in df_ang.columns:
        return None

    out = df_ang.copy()
    out["t"] = pd.to_numeric(out["t_mono_s"], errors="coerce")

    for c in ["roll_deg", "pitch_deg", "yaw_deg"]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
            out[f"{c}_s"] = rolling_mean(out[c], smooth_window)

    keep = ["t"]
    for c in [
        "roll_deg", "pitch_deg", "yaw_deg",
        "roll_deg_s", "pitch_deg_s", "yaw_deg_s"
    ]:
        if c in out.columns:
            keep.append(c)

    out = out[keep].dropna(subset=["t"]).sort_values("t").reset_index(drop=True)
    return out


# ------------------------------------------------------------
# Resampling to common grid
# ------------------------------------------------------------

def merge_on_grid(
    t_grid: np.ndarray,
    gps_df: Optional[pd.DataFrame],
    hr_df: Optional[pd.DataFrame],
    rr_df: Optional[pd.DataFrame],
    acc_df: Optional[pd.DataFrame],
    gyr_df: Optional[pd.DataFrame],
    ang_df: Optional[pd.DataFrame],
) -> pd.DataFrame:
    out = pd.DataFrame({"t_mono": t_grid})

    def add_interp_cols(src: Optional[pd.DataFrame], cols: List[str]):
        nonlocal out
        if src is None or len(src) == 0:
            for c in cols:
                out[c] = np.nan
            return
        x = pd.to_numeric(src["t"], errors="coerce").to_numpy(dtype=float)
        for c in cols:
            if c in src.columns:
                y = pd.to_numeric(src[c], errors="coerce").to_numpy(dtype=float)
                out[c] = safe_interp_series(x, y, t_grid)
            else:
                out[c] = np.nan

    add_interp_cols(gps_df, ["speed_kmh"])
    add_interp_cols(hr_df, ["hr_bpm"])
    add_interp_cols(rr_df, ["rr_ms"])
    add_interp_cols(acc_df, ["ax_g", "ay_g", "az_g", "ax_g_s", "ay_g_s", "az_g_s"])
    add_interp_cols(gyr_df, ["gx_dps", "gy_dps", "gz_dps", "gx_dps_s", "gy_dps_s", "gz_dps_s"])
    add_interp_cols(ang_df, ["roll_deg", "pitch_deg", "yaw_deg", "roll_deg_s", "pitch_deg_s", "yaw_deg_s"])

    return out


def add_time_derivatives(df: pd.DataFrame, dt: float) -> pd.DataFrame:
    out = df.copy()
    for c in ["pitch_deg_s", "yaw_deg_s", "ax_g_s", "ay_g_s", "speed_kmh"]:
        if c in out.columns:
            x = pd.to_numeric(out[c], errors="coerce").to_numpy(dtype=float)
            d = np.full(len(x), np.nan, dtype=float)
            if len(x) >= 2:
                d[1:] = np.diff(x) / dt
            out[f"d_{c}_dt"] = d
    return out


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Build session-level time-series tables from GPS-defined session Excel."
    )
    ap.add_argument("--work-root", required=True, help=r"Example: D:\701lab\work")
    ap.add_argument("--session-excel", required=True, help=r"Example: D:\701lab\work\phaseB\analysis\b3\section\by_run\run_20260308_060029_104785\run_20260308_time.xlsx")
    ap.add_argument("--bike", default="", help="Bike name, e.g. R18 or K1600GT")
    ap.add_argument("--out-dir", default="", help="Output directory (default: work/phaseB/analysis/b3/session_timeseries/by_run)")
    ap.add_argument("--run-start-gps-time", default=None, help="Fallback only. Used if unified_gps.csv mapping is unavailable.")
    ap.add_argument("--smooth-window", type=int, default=11, help="Rolling mean window for IMU-derived series")
    ap.add_argument("--dt-sec", type=float, default=0.25, help="Common output time step in seconds")
    ap.add_argument("--include-ss-se", action="store_true", help="If set, keep SS and SE rows in output")
    ap.add_argument("--debug-counts", action="store_true", help="Print clipped row counts per session for debugging")
    args = ap.parse_args()

    if args.dt_sec <= 0:
        raise SystemExit("[NG] --dt-sec must be > 0")

    work_root = Path(args.work_root)
    run_id, session_df = read_session_excel(Path(args.session_excel))
    if not args.include_ss_se:
        session_df = session_df[session_df["session_id"].isin(["S1", "S2", "S3", "S4", "S5", "S6"])].copy()

    run_dir = work_root / "phaseB" / "derived" / "b2" / "runs" / run_id
    if not run_dir.exists():
        raise SystemExit(f"[NG] run directory not found: {run_dir}")

    df_gps = read_parquet_if_exists(run_dir / "unified_gps.parquet")
    df_hr = read_parquet_if_exists(run_dir / "unified_polar_hr.parquet")
    df_rr = read_parquet_if_exists(run_dir / "unified_polar_rr.parquet")
    df_acc = read_parquet_if_exists(run_dir / "imu_accel.parquet")
    df_gyr = read_parquet_if_exists(run_dir / "imu_gyro.parquet")
    df_ang = read_parquet_if_exists(run_dir / "imu_angle.parquet")
    df_gps_unified = read_csv_if_exists(run_dir / "unified_gps.csv")

    session_df, time_mode = map_sessions_to_mono(
        session_df=session_df,
        df_gps_unified=df_gps_unified,
        run_start_gps_time=args.run_start_gps_time,
    )

    default_out_dir = work_root / "phaseB" / "analysis" / "b3" / "session_timeseries" / "by_run"
    base_out_dir = Path(args.out_dir) if args.out_dir else default_out_dir
    run_out_dir = base_out_dir / run_id
    run_out_dir.mkdir(parents=True, exist_ok=True)

    all_rows = []

    for _, r in session_df.iterrows():
        t_start = float(r["t_start_sec"]) if pd.notna(r["t_start_sec"]) else np.nan
        t_end = float(r["t_end_sec"]) if pd.notna(r["t_end_sec"]) else np.nan
        duration_sec = float(r["duration_sec"])

        if not np.isfinite(t_start) or not np.isfinite(t_end) or t_end <= t_start:
            print(f"[WARN] skip session {r['session_id']} due to invalid mapped time")
            continue

        use_relative_clip = str(time_mode).startswith("fallback")

        if use_relative_clip:
            df_gps_c = clip_by_rel_time(df_gps, "t_mono", t_start, t_end)
            df_hr_c = clip_by_rel_time(df_hr, "t_mono", t_start, t_end)
            df_rr_c = clip_by_rel_time(df_rr, "t_mono", t_start, t_end)
            df_acc_c = clip_by_rel_time(df_acc, "t_mono_s", t_start, t_end)
            df_gyr_c = clip_by_rel_time(df_gyr, "t_mono_s", t_start, t_end)
            df_ang_c = clip_by_rel_time(df_ang, "t_mono_s", t_start, t_end)
        else:
            df_gps_c = clip_by_abs_time(df_gps, "t_mono", t_start, t_end)
            df_hr_c = clip_by_abs_time(df_hr, "t_mono", t_start, t_end)
            df_rr_c = clip_by_abs_time(df_rr, "t_mono", t_start, t_end)
            df_acc_c = clip_by_abs_time(df_acc, "t_mono_s", t_start, t_end)
            df_gyr_c = clip_by_abs_time(df_gyr, "t_mono_s", t_start, t_end)
            df_ang_c = clip_by_abs_time(df_ang, "t_mono_s", t_start, t_end)

        if args.debug_counts:
            clip_mode = "rel" if use_relative_clip else "abs"
            print(
                f"[DBG] {r['session_id']} "
                f"clip={clip_mode} "
                f"mono=({t_start:.3f}, {t_end:.3f}) "
                f"gps={0 if df_gps_c is None else len(df_gps_c)}, "
                f"hr={0 if df_hr_c is None else len(df_hr_c)}, "
                f"rr={0 if df_rr_c is None else len(df_rr_c)}, "
                f"acc={0 if df_acc_c is None else len(df_acc_c)}, "
                f"gyr={0 if df_gyr_c is None else len(df_gyr_c)}, "
                f"ang={0 if df_ang_c is None else len(df_ang_c)}"
            )

        gps_p = prep_gps(df_gps_c)
        hr_p = prep_hr(df_hr_c)
        rr_p = prep_rr(df_rr_c)
        acc_p = prep_acc(df_acc_c, smooth_window=args.smooth_window)
        gyr_p = prep_gyr(df_gyr_c, smooth_window=args.smooth_window)
        ang_p = prep_ang(df_ang_c, smooth_window=args.smooth_window)

        # common grid (include end point)
        n_steps = int(np.floor(duration_sec / args.dt_sec)) + 1
        t_grid_rel = np.arange(n_steps, dtype=float) * args.dt_sec
        t_grid_rel = t_grid_rel[t_grid_rel <= duration_sec + 1e-9]
        t_grid_abs = t_start + t_grid_rel

        merged = merge_on_grid(
            t_grid=t_grid_abs,
            gps_df=gps_p,
            hr_df=hr_p,
            rr_df=rr_p,
            acc_df=acc_p,
            gyr_df=gyr_p,
            ang_df=ang_p,
        )
        merged = add_time_derivatives(merged, dt=args.dt_sec)

        merged.insert(0, "run_id", run_id)
        merged.insert(1, "bike", args.bike)
        merged.insert(2, "session_id", r["session_id"])
        merged.insert(3, "session_name", r["session_name"])
        merged.insert(4, "gps_start_time", r["gps_start_time"])
        merged.insert(5, "gps_end_time", r["gps_end_time"])
        merged.insert(6, "time_mapping_mode", time_mode)
        merged.insert(7, "session_duration_sec", duration_sec)
        merged.insert(8, "t_rel_sec", t_grid_rel)
        merged["grid_index"] = np.arange(len(merged), dtype=int)
        merged["grid_phase_0_1"] = np.where(duration_sec > 0, merged["t_rel_sec"] / duration_sec, np.nan)

        merged["start_N"] = r.get("start_N", np.nan)
        merged["start_E"] = r.get("start_E", np.nan)
        merged["end_N"] = r.get("end_N", np.nan)
        merged["end_E"] = r.get("end_E", np.nan)

        # save per-session
        stem = Path(args.session_excel).stem
        per_session_csv = run_out_dir / f"{stem}_{r['session_id']}_timeseries.csv"
        merged.to_csv(per_session_csv, index=False, encoding="utf-8-sig")
        print(f"[OK] wrote session CSV -> {per_session_csv}")

        all_rows.append(merged)

    if not all_rows:
        raise SystemExit("[NG] no session time-series created")

    all_ts = pd.concat(all_rows, ignore_index=True)

    stem = Path(args.session_excel).stem
    csv_path = run_out_dir / f"{stem}_session_timeseries.csv"
    xlsx_path = run_out_dir / f"{stem}_session_timeseries.xlsx"

    all_ts.to_csv(csv_path, index=False, encoding="utf-8-sig")
    try:
        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
            all_ts.to_excel(writer, index=False, sheet_name="session_timeseries")
        wrote_xlsx = True
    except ModuleNotFoundError:
        wrote_xlsx = False

    print(f"[OK] run_id={run_id}")
    print(f"[OK] time_mapping_mode={time_mode}")
    print(f"[OK] dt_sec={args.dt_sec}")
    print(f"[OK] wrote CSV  -> {csv_path}")
    if wrote_xlsx:
        print(f"[OK] wrote XLSX -> {xlsx_path}")
    else:
        print("[WARN] openpyxl not installed, skipped XLSX output")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())