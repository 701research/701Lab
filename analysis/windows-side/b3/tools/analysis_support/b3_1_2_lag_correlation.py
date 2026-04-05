#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase B3-4: Lagged correlation analysis for 701Lab
[5 selected pairs version / HR-RR range extended]

目的
- 重要な5ペアについて、時間ずれを考慮した相関を見る
- 各ペアの lag-correlation 曲線をPNG保存する
- 最大相関値とそのラグ秒をCSV保存する
- 単独ランの「このランではどうか」を見るための土台を作る

対象5ペア
1) ax_g       <-> pitch_deg   : ±10 s
2) ay_g       <-> gx_dps      : ±10 s
3) gz_dps     <-> roll_deg    : ±10 s
4) speed_kmh  <-> hr_bpm      : ±20 s
5) speed_kmh  <-> rr_ms       : ±20 s

前提データ配置
  work/phaseB/derived/b2/_staging/b2_1_targets.parquet
  work/phaseB/derived/b2/runs/<run_id>/unified_gps.parquet
  work/phaseB/derived/b2/runs/<run_id>/unified_polar_hr.parquet
  work/phaseB/derived/b2/runs/<run_id>/unified_polar_rr.parquet
  work/phaseB/derived/b2/runs/<run_id>/imu_accel.parquet
  work/phaseB/derived/b2/runs/<run_id>/imu_gyro.parquet
  work/phaseB/derived/b2/runs/<run_id>/imu_angle.parquet
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, List, Tuple, Dict

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


# ----------------------------
# 基本ユーティリティ
# ----------------------------

def _read_parquet(p: Path) -> Optional[pd.DataFrame]:
    return pd.read_parquet(p) if p.exists() else None


def _safe_numeric(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _get_rel_time_series(df: pd.DataFrame, tcol: str) -> pd.Series:
    t = _safe_numeric(df[tcol])
    valid = t.dropna()
    if len(valid) == 0:
        return pd.Series(np.full(len(df), np.nan), index=df.index, dtype=float)
    t0 = float(valid.iloc[0])
    return t - t0


def _clip_df_by_rel_time(
    df: Optional[pd.DataFrame],
    tcol: str,
    t_start: Optional[float],
    t_end: Optional[float],
) -> Optional[pd.DataFrame]:
    if df is None or len(df) == 0:
        return df
    if tcol not in df.columns:
        return df

    out = df.copy()
    t_rel = _get_rel_time_series(out, tcol)

    mask = pd.Series(True, index=out.index)
    if t_start is not None:
        mask &= (t_rel >= float(t_start))
    if t_end is not None:
        mask &= (t_rel <= float(t_end))

    return out[mask].copy()


def _asof_merge_on_grid(
    grid: pd.DataFrame,
    src: Optional[pd.DataFrame],
    tcol: str,
    value_cols: List[str],
    tolerance_s: Optional[float] = None,
) -> pd.DataFrame:
    if src is None or len(src) == 0:
        out = grid.copy()
        for c in value_cols:
            out[c] = np.nan
        return out

    use_cols = [tcol] + [c for c in value_cols if c in src.columns]
    tmp = src[use_cols].copy()
    tmp[tcol] = _safe_numeric(tmp[tcol])
    tmp = tmp.dropna(subset=[tcol]).sort_values(tcol)

    if len(tmp) == 0:
        out = grid.copy()
        for c in value_cols:
            out[c] = np.nan
        return out

    tmp["t_rel_s"] = tmp[tcol] - float(tmp[tcol].iloc[0])
    keep_cols = ["t_rel_s"] + [c for c in value_cols if c in tmp.columns]
    tmp = tmp[keep_cols].sort_values("t_rel_s")

    out = pd.merge_asof(
        grid.sort_values("t_rel_s"),
        tmp.sort_values("t_rel_s"),
        on="t_rel_s",
        direction="nearest",
        tolerance=tolerance_s,
    )

    for c in value_cols:
        if c not in out.columns:
            out[c] = np.nan

    return out


def _save_fig(fig, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=160)
    plt.close(fig)


# ----------------------------
# 個別ソースの整形
# ----------------------------

def _prepare_gps_speed(df_gps: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df_gps is None or len(df_gps) == 0:
        return None

    df = df_gps.copy()
    df["name"] = df["name"].astype(str)
    df["value"] = _safe_numeric(df["value"])
    df = df[df["name"] == "speed_mps"].copy()
    if len(df) == 0:
        return None

    df["speed_kmh"] = df["value"] * 3.6
    return df[["t_mono", "speed_kmh"]].copy()


def _prepare_hr(df_hr: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df_hr is None or len(df_hr) == 0:
        return None

    df = df_hr.copy()
    df["hr_bpm"] = _safe_numeric(df["value"])
    df = df.dropna(subset=["t_mono", "hr_bpm"]).copy()
    if len(df) == 0:
        return None

    return df[["t_mono", "hr_bpm"]].copy()


def _prepare_rr(df_rr: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df_rr is None or len(df_rr) == 0:
        return None

    df = df_rr.copy()
    df["rr_ms"] = _safe_numeric(df["value"])
    df = df.dropna(subset=["t_mono", "rr_ms"]).copy()
    df = df[(df["rr_ms"] >= 200) & (df["rr_ms"] <= 3000)].copy()
    if len(df) == 0:
        return None

    return df[["t_mono", "rr_ms"]].copy()


def _prepare_imu_acc(df_acc: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df_acc is None or len(df_acc) == 0:
        return None

    df = df_acc.copy()
    for c in ["ax_g", "ay_g", "az_g"]:
        if c in df.columns:
            df[c] = _safe_numeric(df[c])

    cols = ["t_mono_s"] + [c for c in ["ax_g", "ay_g", "az_g"] if c in df.columns]
    df = df[cols].dropna(subset=["t_mono_s"]).copy()
    if len(df) == 0:
        return None
    return df


def _prepare_imu_gyr(df_gyr: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df_gyr is None or len(df_gyr) == 0:
        return None

    df = df_gyr.copy()
    for c in ["gx_dps", "gy_dps", "gz_dps"]:
        if c in df.columns:
            df[c] = _safe_numeric(df[c])

    cols = ["t_mono_s"] + [c for c in ["gx_dps", "gy_dps", "gz_dps"] if c in df.columns]
    df = df[cols].dropna(subset=["t_mono_s"]).copy()
    if len(df) == 0:
        return None
    return df


def _prepare_imu_ang(df_ang: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df_ang is None or len(df_ang) == 0:
        return None

    df = df_ang.copy()
    for c in ["roll_deg", "pitch_deg", "yaw_deg"]:
        if c in df.columns:
            df[c] = _safe_numeric(df[c])

    cols = ["t_mono_s"] + [c for c in ["roll_deg", "pitch_deg", "yaw_deg"] if c in df.columns]
    df = df[cols].dropna(subset=["t_mono_s"]).copy()
    if len(df) == 0:
        return None
    return df


# ----------------------------
# run単位の共通時系列作成
# ----------------------------

def build_run_feature_table(
    run_dir: Path,
    run_id: str,
    dt_s: float,
    tolerance_s: Optional[float],
    t_start: Optional[float],
    t_end: Optional[float],
) -> Optional[pd.DataFrame]:
    df_gps = _read_parquet(run_dir / "unified_gps.parquet")
    df_hr = _read_parquet(run_dir / "unified_polar_hr.parquet")
    df_rr = _read_parquet(run_dir / "unified_polar_rr.parquet")
    df_acc = _read_parquet(run_dir / "imu_accel.parquet")
    df_gyr = _read_parquet(run_dir / "imu_gyro.parquet")
    df_ang = _read_parquet(run_dir / "imu_angle.parquet")

    df_gps = _clip_df_by_rel_time(df_gps, "t_mono", t_start, t_end)
    df_hr = _clip_df_by_rel_time(df_hr, "t_mono", t_start, t_end)
    df_rr = _clip_df_by_rel_time(df_rr, "t_mono", t_start, t_end)
    df_acc = _clip_df_by_rel_time(df_acc, "t_mono_s", t_start, t_end)
    df_gyr = _clip_df_by_rel_time(df_gyr, "t_mono_s", t_start, t_end)
    df_ang = _clip_df_by_rel_time(df_ang, "t_mono_s", t_start, t_end)

    gps = _prepare_gps_speed(df_gps)
    hr = _prepare_hr(df_hr)
    rr = _prepare_rr(df_rr)
    acc = _prepare_imu_acc(df_acc)
    gyr = _prepare_imu_gyr(df_gyr)
    ang = _prepare_imu_ang(df_ang)

    t_ends = []

    for df, tcol in [
        (gps, "t_mono"),
        (hr, "t_mono"),
        (rr, "t_mono"),
        (acc, "t_mono_s"),
        (gyr, "t_mono_s"),
        (ang, "t_mono_s"),
    ]:
        if df is not None and len(df) > 0:
            t_rel = _get_rel_time_series(df, tcol)
            if t_rel.notna().sum() > 0:
                t_ends.append(float(t_rel.dropna().max()))

    if len(t_ends) == 0:
        return None

    t_max = max(t_ends)
    if not np.isfinite(t_max) or t_max <= 0:
        return None

    grid = pd.DataFrame({"t_rel_s": np.arange(0.0, t_max + 1e-9, dt_s)})

    out = grid.copy()
    out = _asof_merge_on_grid(out, gps, "t_mono", ["speed_kmh"], tolerance_s)
    out = _asof_merge_on_grid(out, hr, "t_mono", ["hr_bpm"], tolerance_s)
    out = _asof_merge_on_grid(out, rr, "t_mono", ["rr_ms"], tolerance_s)
    out = _asof_merge_on_grid(out, acc, "t_mono_s", ["ax_g", "ay_g", "az_g"], tolerance_s)
    out = _asof_merge_on_grid(out, gyr, "t_mono_s", ["gx_dps", "gy_dps", "gz_dps"], tolerance_s)
    out = _asof_merge_on_grid(out, ang, "t_mono_s", ["roll_deg", "pitch_deg", "yaw_deg"], tolerance_s)
    out["run_id"] = run_id
    return out


# ----------------------------
# ラグ相関
# ----------------------------

def _zscore(s: pd.Series) -> pd.Series:
    x = _safe_numeric(s).astype(float)
    mu = x.mean(skipna=True)
    sd = x.std(skipna=True, ddof=0)
    if (not np.isfinite(mu)) or (not np.isfinite(sd)) or sd <= 0:
        return pd.Series(np.full(len(x), np.nan), index=x.index, dtype=float)
    return (x - mu) / sd


def compute_lagged_corr(
    df: pd.DataFrame,
    xcol: str,
    ycol: str,
    dt_s: float,
    max_lag_s: float,
    min_overlap: int,
) -> pd.DataFrame:
    """
    lag > 0:
      x が先、y が後
      corr( x[t], y[t + lag] )

    lag < 0:
      y が先、x が後
    """
    if xcol not in df.columns or ycol not in df.columns:
        return pd.DataFrame(columns=["lag_step", "lag_s", "corr", "n_overlap"])

    x = _zscore(df[xcol])
    y = _zscore(df[ycol])

    max_lag_step = int(round(max_lag_s / dt_s))
    rows = []

    for lag in range(-max_lag_step, max_lag_step + 1):
        if lag > 0:
            xs = x.iloc[:-lag]
            ys = y.iloc[lag:]
        elif lag < 0:
            k = -lag
            xs = x.iloc[k:]
            ys = y.iloc[:-k]
        else:
            xs = x
            ys = y

        pair = pd.DataFrame({"x": xs.to_numpy(), "y": ys.to_numpy()}).dropna()
        n = len(pair)

        if n < min_overlap:
            corr = np.nan
        else:
            corr = pair["x"].corr(pair["y"], method="pearson")

        rows.append({
            "lag_step": lag,
            "lag_s": lag * dt_s,
            "corr": corr,
            "n_overlap": n,
        })

    return pd.DataFrame(rows)


def summarize_lagcorr(df_lag: pd.DataFrame, xcol: str, ycol: str) -> dict:
    out = {
        "x": xcol,
        "y": ycol,
        "best_lag_s_signed": np.nan,
        "best_corr_signed": np.nan,
        "best_lag_s_abs": np.nan,
        "best_corr_abs": np.nan,
        "corr_at_zero_lag": np.nan,
    }

    if df_lag is None or len(df_lag) == 0:
        return out

    valid = df_lag.dropna(subset=["corr"]).copy()
    if len(valid) == 0:
        return out

    idx_signed = valid["corr"].idxmax()
    row_signed = valid.loc[idx_signed]
    out["best_lag_s_signed"] = float(row_signed["lag_s"])
    out["best_corr_signed"] = float(row_signed["corr"])

    valid["corr_abs"] = valid["corr"].abs()
    idx_abs = valid["corr_abs"].idxmax()
    row_abs = valid.loc[idx_abs]
    out["best_lag_s_abs"] = float(row_abs["lag_s"])
    out["best_corr_abs"] = float(row_abs["corr"])

    zero = valid[np.isclose(valid["lag_s"], 0.0)]
    if len(zero) > 0:
        out["corr_at_zero_lag"] = float(zero.iloc[0]["corr"])

    return out


def draw_lagcorr_plot(
    df_lag: pd.DataFrame,
    xcol: str,
    ycol: str,
    out_path: Path,
    title_suffix: str = "",
) -> None:
    fig = plt.figure(figsize=(9, 5))
    ax = fig.add_subplot(1, 1, 1)

    ax.plot(df_lag["lag_s"], df_lag["corr"])
    ax.axvline(0.0, linestyle="--", linewidth=1)
    ax.axhline(0.0, linestyle="--", linewidth=1)

    valid = df_lag.dropna(subset=["corr"]).copy()
    if len(valid) > 0:
        idx_abs = valid["corr"].abs().idxmax()
        best = valid.loc[idx_abs]
        ax.scatter([best["lag_s"]], [best["corr"]], s=50)
        ax.text(
            float(best["lag_s"]),
            float(best["corr"]),
            f"  lag={best['lag_s']:.2f}s, r={best['corr']:.2f}",
            va="bottom",
            ha="left",
            fontsize=9,
        )

    ax.set_title(f"Lagged correlation: {xcol} -> {ycol}{title_suffix}")
    ax.set_xlabel("lag (s)  [lag > 0 means x leads y]")
    ax.set_ylabel("Pearson correlation")
    ax.grid(True, alpha=0.3)

    _save_fig(fig, out_path)


# ----------------------------
# 出力先決定
# ----------------------------

def _resolve_output_dir(work_root: Path, run_id: str) -> Path:
    base_dir = work_root / "phaseB" / "analysis" / "b3" / "lag_correlation"
    if run_id:
        return base_dir / "by_run" / run_id
    return base_dir / "global"


# ----------------------------
# main
# ----------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-root", default=r"D:\701lab\work")
    ap.add_argument("--run-id", default="", help="Process only one run_id")
    ap.add_argument("--dt", type=float, default=0.10, help="Common time grid step [s]")
    ap.add_argument("--tolerance", type=float, default=0.25, help="merge_asof tolerance [s]")
    ap.add_argument("--t-start", type=float, default=None, help="Relative start time [s]")
    ap.add_argument("--t-end", type=float, default=None, help="Relative end time [s]")
    ap.add_argument("--max-lag", type=float, default=10.0, help="Default max lag for non-HR/RR pairs [s]")
    ap.add_argument("--max-lag-hr-rr", type=float, default=20.0, help="Max lag for HR/RR related pairs [s]")
    ap.add_argument("--min-overlap", type=int, default=30, help="Minimum valid overlap samples for correlation")
    args = ap.parse_args()

    if args.dt <= 0:
        raise SystemExit("[NG] --dt must be > 0")
    if args.tolerance <= 0:
        raise SystemExit("[NG] --tolerance must be > 0")
    if args.max_lag <= 0:
        raise SystemExit("[NG] --max-lag must be > 0")
    if args.max_lag_hr_rr <= 0:
        raise SystemExit("[NG] --max-lag-hr-rr must be > 0")
    if args.min_overlap < 3:
        raise SystemExit("[NG] --min-overlap must be >= 3")
    if (args.t_start is not None) and (args.t_end is not None) and (args.t_end < args.t_start):
        raise SystemExit("[NG] t_end must be >= t_start")

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
    out_dir = _resolve_output_dir(work_root, args.run_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    merged_all = []

    for _, row in targets.iterrows():
        run_id = str(row["run_id"])
        run_dir = derived_runs / run_id
        if not run_dir.exists():
            print(f"[WARN] {run_id}: missing run dir -> {run_dir}")
            continue

        df_run = build_run_feature_table(
            run_dir=run_dir,
            run_id=run_id,
            dt_s=args.dt,
            tolerance_s=args.tolerance,
            t_start=args.t_start,
            t_end=args.t_end,
        )

        if df_run is None or len(df_run) == 0:
            print(f"[WARN] {run_id}: no usable data")
            continue

        merged_all.append(df_run)
        print(f"[OK] {run_id}: rows={len(df_run)}")

    if len(merged_all) == 0:
        raise SystemExit("[NG] no merged data was built")

    df_all = pd.concat(merged_all, axis=0, ignore_index=True)
    df_all.to_parquet(out_dir / "merged_timeseries.parquet", index=False)

    pairs: List[Tuple[str, str]] = [
        ("ax_g", "pitch_deg"),
        ("ay_g", "gx_dps"),
        ("gz_dps", "roll_deg"),
        ("speed_kmh", "hr_bpm"),
        ("speed_kmh", "rr_ms"),
    ]

    pair_max_lag: Dict[Tuple[str, str], float] = {
        ("ax_g", "pitch_deg"): args.max_lag,
        ("ay_g", "gx_dps"): args.max_lag,
        ("gz_dps", "roll_deg"): args.max_lag,
        ("speed_kmh", "hr_bpm"): args.max_lag_hr_rr,
        ("speed_kmh", "rr_ms"): args.max_lag_hr_rr,
    }

    summaries = []

    if args.run_id:
        title_suffix = f" - {args.run_id}"
    else:
        title_suffix = " - global"

    for xcol, ycol in pairs:
        if xcol not in df_all.columns or ycol not in df_all.columns:
            print(f"[WARN] skip pair: {xcol} <-> {ycol} (missing column)")
            continue

        max_lag_s = pair_max_lag[(xcol, ycol)]

        df_lag = compute_lagged_corr(
            df=df_all,
            xcol=xcol,
            ycol=ycol,
            dt_s=args.dt,
            max_lag_s=max_lag_s,
            min_overlap=args.min_overlap,
        )

        stem = f"lagcorr_{xcol}__{ycol}"
        df_lag.to_csv(out_dir / f"{stem}.csv", index=False, encoding="utf-8-sig")

        draw_lagcorr_plot(
            df_lag=df_lag,
            xcol=xcol,
            ycol=ycol,
            out_path=out_dir / f"{stem}.png",
            title_suffix=title_suffix,
        )

        s = summarize_lagcorr(df_lag, xcol, ycol)
        s["max_lag_s_used"] = max_lag_s
        summaries.append(s)

        print(f"[OK] pair: {xcol} <-> {ycol} (max_lag={max_lag_s}s)")

    summary_df = pd.DataFrame(summaries)
    summary_df.to_csv(out_dir / "lag_summary.csv", index=False, encoding="utf-8-sig")

    print("[OK] wrote:")
    print(f"  {out_dir / 'merged_timeseries.parquet'}")
    print(f"  {out_dir / 'lag_summary.csv'}")
    for xcol, ycol in pairs:
        stem = f"lagcorr_{xcol}__{ycol}"
        print(f"  {out_dir / (stem + '.csv')}")
        print(f"  {out_dir / (stem + '.png')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())