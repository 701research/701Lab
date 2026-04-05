#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase B3-1: Overall correlation analysis for 701Lab
[global / by_run output version]

目的
- 全 run を通した主要パラメータの全体相関を確認する
- Pearson / Spearman の相関行列を出力する
- 相関ヒートマップをPNG保存する
- 後段の「車種別」「セッション別」解析の土台を作る

前提データ配置
  work/phaseB/derived/b2/_staging/b2_1_targets.parquet
  work/phaseB/derived/b2/runs/<run_id>/unified_gps.parquet
  work/phaseB/derived/b2/runs/<run_id>/unified_polar_hr.parquet
  work/phaseB/derived/b2/runs/<run_id>/unified_polar_rr.parquet
  work/phaseB/derived/b2/runs/<run_id>/imu_accel.parquet
  work/phaseB/derived/b2/runs/<run_id>/imu_gyro.parquet
  work/phaseB/derived/b2/runs/<run_id>/imu_angle.parquet

出力
  全ランまとめ:
    work/phaseB/analysis/b3/correlation/global/
      merged_timeseries.parquet
      correlation_pearson.csv
      correlation_spearman.csv
      missing_rate.csv
      heatmap_pearson.png
      heatmap_spearman.png

  単独ラン指定時:
    work/phaseB/analysis/b3/correlation/by_run/<run_id>/
      merged_timeseries.parquet
      correlation_pearson.csv
      correlation_spearman.csv
      missing_rate.csv
      heatmap_pearson.png
      heatmap_spearman.png

主な考え方
- runごとに相対時間 t_rel_s を作る
- 共通時間グリッドへ asof マージして主要変数を整列
- run を縦結合して全体相関を計算
- NaN が多い列の欠損率も保存

注意
- GPS, HR, RR は unified_* 側の t_mono を使う
- IMU は t_mono_s を使う
- RR は瞬時RR列として時系列的に並べる
- 現時点では「段階1: 全体相関」専用
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, List

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
    """
    grid: 必ず t_rel_s を持つ
    src : tcol を持つ
    value_cols を t_rel_s 基準で merge_asof
    """
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
# 相関と可視化
# ----------------------------

def compute_missing_rate(df: pd.DataFrame, feature_cols: List[str]) -> pd.DataFrame:
    rows = []
    n = len(df)
    for c in feature_cols:
        miss = df[c].isna().sum()
        rows.append({
            "feature": c,
            "n_total": n,
            "n_missing": int(miss),
            "missing_rate": float(miss / n) if n > 0 else np.nan,
        })
    return pd.DataFrame(rows)


def draw_corr_heatmap(corr: pd.DataFrame, title: str, out_path: Path) -> None:
    labels = list(corr.columns)
    vals = corr.to_numpy(dtype=float)

    fig, ax = plt.subplots(figsize=(10, 8))
    im = ax.imshow(vals, vmin=-1.0, vmax=1.0, aspect="auto")
    ax.set_title(title)

    ax.set_xticks(np.arange(len(labels)))
    ax.set_yticks(np.arange(len(labels)))
    ax.set_xticklabels(labels, rotation=60, ha="right")
    ax.set_yticklabels(labels)

    for i in range(vals.shape[0]):
        for j in range(vals.shape[1]):
            v = vals[i, j]
            txt = "" if not np.isfinite(v) else f"{v:.2f}"
            ax.text(j, i, txt, ha="center", va="center", fontsize=8)

    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("correlation")

    _save_fig(fig, out_path)


# ----------------------------
# 出力先決定
# ----------------------------

def _resolve_output_dir(work_root: Path, run_id: str) -> Path:
    base_dir = work_root / "phaseB" / "analysis" / "b3" / "correlation"
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
    ap.add_argument("--dt", type=float, default=0.10, help="Common time grid step [s], default 0.10 = 10 Hz")
    ap.add_argument("--tolerance", type=float, default=0.25, help="merge_asof tolerance [s]")
    ap.add_argument("--t-start", type=float, default=None, help="Relative start time [s]")
    ap.add_argument("--t-end", type=float, default=None, help="Relative end time [s]")
    ap.add_argument("--min-valid-ratio", type=float, default=0.30, help="Drop feature if valid ratio < this threshold")
    args = ap.parse_args()

    if args.dt <= 0:
        raise SystemExit("[NG] --dt must be > 0")
    if args.tolerance <= 0:
        raise SystemExit("[NG] --tolerance must be > 0")
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

    feature_cols = [
        "speed_kmh",
        "ax_g", "ay_g", "az_g",
        "gx_dps", "gy_dps", "gz_dps",
        "roll_deg", "pitch_deg", "yaw_deg",
        "hr_bpm",
        "rr_ms",
    ]

    feature_cols = [c for c in feature_cols if c in df_all.columns]

    missing_df = compute_missing_rate(df_all, feature_cols)
    missing_df.to_csv(out_dir / "missing_rate.csv", index=False, encoding="utf-8-sig")

    keep_features = []
    for _, r in missing_df.iterrows():
        valid_ratio = 1.0 - float(r["missing_rate"])
        if valid_ratio >= args.min_valid_ratio:
            keep_features.append(str(r["feature"]))
        else:
            print(f"[INFO] drop low-valid feature: {r['feature']} (valid_ratio={valid_ratio:.3f})")

    if len(keep_features) < 2:
        raise SystemExit("[NG] too few valid features after filtering")

    df_all.to_parquet(out_dir / "merged_timeseries.parquet", index=False)

    pearson = df_all[keep_features].corr(method="pearson")
    spearman = df_all[keep_features].corr(method="spearman")

    pearson.to_csv(out_dir / "correlation_pearson.csv", encoding="utf-8-sig")
    spearman.to_csv(out_dir / "correlation_spearman.csv", encoding="utf-8-sig")

    if args.run_id:
        title_pe = f"Correlation Matrix (Pearson) - {args.run_id}"
        title_sp = f"Correlation Matrix (Spearman) - {args.run_id}"
    else:
        title_pe = "Overall Correlation Matrix (Pearson)"
        title_sp = "Overall Correlation Matrix (Spearman)"

    draw_corr_heatmap(
        pearson,
        title_pe,
        out_dir / "heatmap_pearson.png",
    )
    draw_corr_heatmap(
        spearman,
        title_sp,
        out_dir / "heatmap_spearman.png",
    )

    print("[OK] wrote:")
    print(f"  {out_dir / 'merged_timeseries.parquet'}")
    print(f"  {out_dir / 'missing_rate.csv'}")
    print(f"  {out_dir / 'correlation_pearson.csv'}")
    print(f"  {out_dir / 'correlation_spearman.csv'}")
    print(f"  {out_dir / 'heatmap_pearson.png'}")
    print(f"  {out_dir / 'heatmap_spearman.png'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())