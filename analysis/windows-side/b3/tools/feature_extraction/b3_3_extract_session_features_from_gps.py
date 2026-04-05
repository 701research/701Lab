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


def safe_mean(s: pd.Series) -> float:
    x = pd.to_numeric(s, errors="coerce")
    return float(x.mean()) if x.notna().any() else np.nan


def safe_std(s: pd.Series) -> float:
    x = pd.to_numeric(s, errors="coerce")
    return float(x.std(ddof=0)) if x.notna().any() else np.nan


def safe_max(s: pd.Series) -> float:
    x = pd.to_numeric(s, errors="coerce")
    return float(x.max()) if x.notna().any() else np.nan


def safe_min(s: pd.Series) -> float:
    x = pd.to_numeric(s, errors="coerce")
    return float(x.min()) if x.notna().any() else np.nan


def energy_from_series(s: pd.Series) -> float:
    x = pd.to_numeric(s, errors="coerce")
    x = x[np.isfinite(x)]
    return float(np.mean(np.square(x))) if len(x) else np.nan


def abs_mean_from_series(s: pd.Series) -> float:
    x = pd.to_numeric(s, errors="coerce")
    x = x[np.isfinite(x)]
    return float(np.mean(np.abs(x))) if len(x) else np.nan


def parse_hms_to_seconds(hms: str) -> int:
    parts = str(hms).strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid HH:MM:SS string: {hms}")
    hh, mm, ss = map(int, parts)
    return hh * 3600 + mm * 60 + ss


def normalize_minmax_per_run(df: pd.DataFrame, source_to_norm: Dict[str, str]) -> pd.DataFrame:
    out = df.copy()
    for _, idx in out.groupby("run_id").groups.items():
        for norm_col, src_col in source_to_norm.items():
            if src_col not in out.columns:
                out.loc[idx, norm_col] = np.nan
                continue
            x = pd.to_numeric(out.loc[idx, src_col], errors="coerce")
            finite = x[np.isfinite(x)]
            if len(finite) == 0:
                out.loc[idx, norm_col] = np.nan
                continue
            xmin = float(finite.min())
            xmax = float(finite.max())
            if xmax == xmin:
                out.loc[idx, norm_col] = 0.5
            else:
                out.loc[idx, norm_col] = (x - xmin) / (xmax - xmin)
    return out


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


def build_clock_to_mono_map(df_gps_unified: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """
    Build local-clock -> t_mono mapping table from unified_gps.csv.

    Expected columns:
      - t_wall : local wall-clock timestamp string
      - t_mono : monotonic time

    Returns DataFrame with:
      - clock_sec
      - t_mono
    """
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
    """
    Convert Excel session HH:MM:SS to actual t_mono using unified_gps.csv t_wall.

    Fallback:
      if unified_gps.csv mapping is unavailable and run_start_gps_time is provided,
      use relative seconds from that clock origin.
    """
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
# Feature extraction per modality
# ------------------------------------------------------------

def extract_gps_features(df_gps: Optional[pd.DataFrame]) -> Dict[str, float]:
    out = {
        "mean_speed_kmh": np.nan,
        "max_speed_kmh": np.nan,
        "std_speed_kmh": np.nan,
        "speed_range_kmh": np.nan,
    }
    if df_gps is None or len(df_gps) == 0:
        return out
    if not {"name", "value"}.issubset(df_gps.columns):
        return out
    sp = df_gps[df_gps["name"].astype(str) == "speed_mps"].copy()
    if len(sp) == 0:
        return out
    speed_kmh = pd.to_numeric(sp["value"], errors="coerce") * 3.6
    out["mean_speed_kmh"] = safe_mean(speed_kmh)
    out["max_speed_kmh"] = safe_max(speed_kmh)
    out["std_speed_kmh"] = safe_std(speed_kmh)
    out["speed_range_kmh"] = safe_max(speed_kmh) - safe_min(speed_kmh)
    return out


def extract_hr_features(df_hr: Optional[pd.DataFrame], df_rr: Optional[pd.DataFrame]) -> Dict[str, float]:
    out = {
        "mean_hr_bpm": np.nan,
        "max_hr_bpm": np.nan,
        "std_hr_bpm": np.nan,
        "mean_rr_ms": np.nan,
    }
    if df_hr is not None and len(df_hr) > 0 and "value" in df_hr.columns:
        hr = pd.to_numeric(df_hr["value"], errors="coerce")
        out["mean_hr_bpm"] = safe_mean(hr)
        out["max_hr_bpm"] = safe_max(hr)
        out["std_hr_bpm"] = safe_std(hr)
    if df_rr is not None and len(df_rr) > 0 and "value" in df_rr.columns:
        rr = pd.to_numeric(df_rr["value"], errors="coerce")
        rr = rr[(rr >= 200) & (rr <= 3000)]
        out["mean_rr_ms"] = safe_mean(rr)
    return out


def compute_event_rate(
    signal: pd.Series,
    threshold: float,
    duration_sec: float,
    use_diff: bool,
) -> float:
    x = pd.to_numeric(signal, errors="coerce")
    x = x[np.isfinite(x)]
    if len(x) == 0 or duration_sec <= 0:
        return np.nan
    target = np.abs(np.diff(x.to_numpy())) if use_diff else np.abs(x.to_numpy())
    if len(target) == 0:
        return 0.0
    cnt = int(np.sum(target > threshold))
    return float(cnt / duration_sec)


def extract_accel_features(
    df_acc: Optional[pd.DataFrame],
    duration_sec: float,
    smooth_window: int,
    ax_threshold: float,
    ax_event_use_diff: bool,
) -> Dict[str, float]:
    out = {
        "mean_ax_g": np.nan,
        "std_ax_g": np.nan,
        "ax_abs_mean": np.nan,
        "ax_event_rate": np.nan,
        "mean_ay_g": np.nan,
        "std_ay_g": np.nan,
        "ay_energy": np.nan,
        "ay_abs_mean": np.nan,
    }
    if df_acc is None or len(df_acc) == 0:
        return out

    work = df_acc.copy()
    if "ax_g" in work.columns:
        work["ax_g_s"] = rolling_mean(work["ax_g"], smooth_window)
        ax = work["ax_g_s"]
        out["mean_ax_g"] = safe_mean(ax)
        out["std_ax_g"] = safe_std(ax)
        out["ax_abs_mean"] = abs_mean_from_series(ax)
        out["ax_event_rate"] = compute_event_rate(ax, ax_threshold, duration_sec, ax_event_use_diff)

    if "ay_g" in work.columns:
        work["ay_g_s"] = rolling_mean(work["ay_g"], smooth_window)
        ay = work["ay_g_s"]
        out["mean_ay_g"] = safe_mean(ay)
        out["std_ay_g"] = safe_std(ay)
        out["ay_energy"] = energy_from_series(ay)
        out["ay_abs_mean"] = abs_mean_from_series(ay)
    return out


def extract_angle_features(df_ang: Optional[pd.DataFrame], smooth_window: int) -> Dict[str, float]:
    out = {
        "mean_pitch_deg": np.nan,
        "std_pitch_deg": np.nan,
        "pitch_range_deg": np.nan,
        "pitch_rate_mean": np.nan,
        "pitch_rate_std": np.nan,
    }
    if df_ang is None or len(df_ang) == 0 or "pitch_deg" not in df_ang.columns:
        return out

    work = df_ang.copy().sort_values("t_mono_s")
    work["pitch_deg_s"] = rolling_mean(work["pitch_deg"], smooth_window)
    pitch = pd.to_numeric(work["pitch_deg_s"], errors="coerce")

    out["mean_pitch_deg"] = safe_mean(pitch)
    out["std_pitch_deg"] = safe_std(pitch)
    out["pitch_range_deg"] = safe_max(pitch) - safe_min(pitch)

    if "t_mono_s" in work.columns:
        t = pd.to_numeric(work["t_mono_s"], errors="coerce").to_numpy(dtype=float)
        y = pitch.to_numpy(dtype=float)
        mask = np.isfinite(t) & np.isfinite(y)
        t = t[mask]
        y = y[mask]
        if len(t) >= 2:
            dt = np.diff(t)
            dy = np.diff(y)
            valid = dt > 0
            rate = dy[valid] / dt[valid] if np.any(valid) else np.array([])
            if len(rate):
                out["pitch_rate_mean"] = float(np.mean(rate))
                out["pitch_rate_std"] = float(np.std(rate))
    return out


def extract_gyro_features(df_gyr: Optional[pd.DataFrame], smooth_window: int) -> Dict[str, float]:
    out = {
        "mean_gx_dps": np.nan,
        "std_gx_dps": np.nan,
        "gx_energy": np.nan,
        "mean_gz_dps": np.nan,
        "std_gz_dps": np.nan,
    }
    if df_gyr is None or len(df_gyr) == 0:
        return out

    work = df_gyr.copy()
    if "gx_dps" in work.columns:
        work["gx_dps_s"] = rolling_mean(work["gx_dps"], smooth_window)
        gx = work["gx_dps_s"]
        out["mean_gx_dps"] = safe_mean(gx)
        out["std_gx_dps"] = safe_std(gx)
        out["gx_energy"] = energy_from_series(gx)

    if "gz_dps" in work.columns:
        work["gz_dps_s"] = rolling_mean(work["gz_dps"], smooth_window)
        gz = work["gz_dps_s"]
        out["mean_gz_dps"] = safe_mean(gz)
        out["std_gz_dps"] = safe_std(gz)
    return out


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Extract session-level features from GPS-defined session Excel.")
    ap.add_argument("--work-root", required=True, help=r"Example: D:\701lab\work")
    ap.add_argument("--session-excel", required=True, help=r"Example: D:\701lab\work\phaseB\analysis\b3\section\by_run\run_20260308_060029_104785\run_20260308_time.xlsx")
    ap.add_argument("--bike", default="", help="Bike name, e.g. R18 or K1600GT")
    ap.add_argument("--out-dir", default="", help="Output directory (default: work/phaseB/analysis/b3/session_features/by_run)")
    ap.add_argument("--run-start-gps-time", default=None, help="Fallback only. Used if unified_gps.csv mapping is unavailable.")
    ap.add_argument("--smooth-window", type=int, default=11, help="Rolling mean window for IMU-derived features")
    ap.add_argument("--ax-threshold", type=float, default=0.03, help="Threshold for ax_event_rate in g or delta-g")
    ap.add_argument("--ax-event-use-diff", action="store_true", help="Use abs(diff(ax_g)) instead of abs(ax_g) for event counting")
    ap.add_argument("--include-ss-se", action="store_true", help="If set, keep SS and SE rows in output")
    ap.add_argument("--debug-counts", action="store_true", help="Print clipped row counts per session for debugging")
    args = ap.parse_args()

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

    rows: List[Dict[str, float]] = []
    for _, r in session_df.iterrows():
        t_start = float(r["t_start_sec"]) if pd.notna(r["t_start_sec"]) else np.nan
        t_end = float(r["t_end_sec"]) if pd.notna(r["t_end_sec"]) else np.nan
        duration_sec = float(r["duration_sec"])

        if not np.isfinite(t_start) or not np.isfinite(t_end):
            df_gps_c = df_hr_c = df_rr_c = df_acc_c = df_gyr_c = df_ang_c = None
        else:
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
            clip_mode = "rel" if (np.isfinite(t_start) and np.isfinite(t_end) and str(time_mode).startswith("fallback")) else "abs"
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

        row = {
            "run_id": run_id,
            "bike": args.bike,
            "session_id": r["session_id"],
            "session_name": r["session_name"],
            "gps_start_time": r["gps_start_time"],
            "gps_end_time": r["gps_end_time"],
            "t_start_sec": t_start,
            "t_end_sec": t_end,
            "duration_sec": duration_sec,
            "start_N": r.get("start_N", np.nan),
            "start_E": r.get("start_E", np.nan),
            "end_N": r.get("end_N", np.nan),
            "end_E": r.get("end_E", np.nan),
            "time_mapping_mode": time_mode,
        }
        row.update(extract_gps_features(df_gps_c))
        row.update(extract_hr_features(df_hr_c, df_rr_c))
        row.update(extract_accel_features(
            df_acc_c,
            duration_sec=duration_sec,
            smooth_window=args.smooth_window,
            ax_threshold=args.ax_threshold,
            ax_event_use_diff=args.ax_event_use_diff,
        ))
        row.update(extract_angle_features(df_ang_c, smooth_window=args.smooth_window))
        row.update(extract_gyro_features(df_gyr_c, smooth_window=args.smooth_window))
        rows.append(row)

    feat = pd.DataFrame(rows)

    feat = normalize_minmax_per_run(
        feat,
        {
            "speed_n": "mean_speed_kmh",
            "speed_var_n": "std_speed_kmh",
            "ax_n": "ax_event_rate",
            "pitch_n": "mean_pitch_deg",
            "pitch_var_n": "std_pitch_deg",
            "hr_n": "mean_hr_bpm",
            "ay_n": "ay_energy",
        },
    )

    default_out_dir = work_root / "phaseB" / "analysis" / "b3" / "session_features" / "by_run"
    base_out_dir = Path(args.out_dir) if args.out_dir else default_out_dir

    run_out_dir = base_out_dir / run_id
    run_out_dir.mkdir(parents=True, exist_ok=True)

    stem = Path(args.session_excel).stem
    csv_path = run_out_dir / f"{stem}_session_features.csv"
    xlsx_path = run_out_dir / f"{stem}_session_features.xlsx"

    feat.to_csv(csv_path, index=False, encoding="utf-8-sig")
    try:
        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
            feat.to_excel(writer, index=False, sheet_name="session_features")
        wrote_xlsx = True
    except ModuleNotFoundError:
        wrote_xlsx = False

    print(f"[OK] run_id={run_id}")
    print(f"[OK] time_mapping_mode={time_mode}")
    print(f"[OK] wrote CSV  -> {csv_path}")
    if wrote_xlsx:
        print(f"[OK] wrote XLSX -> {xlsx_path}")
    else:
        print("[WARN] openpyxl not installed, skipped XLSX output")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())