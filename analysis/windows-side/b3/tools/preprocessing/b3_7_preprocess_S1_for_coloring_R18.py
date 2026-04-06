# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


# =========================================================
# 基本設定
# =========================================================
DEFAULT_BASE_DIR = r"D:\701lab\work\phaseB\analysis\b3\session_timeseries\by_run"
DEFAULT_RUN_ID = "run_20260322_054454_699988"
DEFAULT_SECTION = "S1"

# S1で使う必須列
# R18では ay 系も明示的に取り込む
REQUIRED_COLUMNS = [
    "t_rel_sec",
    "d_speed_kmh_dt",
    "ax_g_s",
    "ay_g_s",
    "pitch_deg_s",
    "d_pitch_deg_s_dt",
    "yaw_deg_s",
    "d_yaw_deg_s_dt",
]

# 任意列
OPTIONAL_COLUMNS = [
    "d_ay_g_s_dt",
]

# 平滑化窓
# S1は導入なので全体に少し滑らかめ
SMOOTH_WINDOWS = {
    "d_speed_kmh_dt": 13,     # 呼吸包絡
    "ax_g_s": 5,              # 前後アクセント
    "ay_g_s": 7,              # 横方向の張りはやや滑らかに
    "pitch_deg_s": 9,         # 陰影
    "d_pitch_deg_s_dt": 5,    # 微小イベント
    "yaw_deg_s": 7,           # 向きの気配
    "d_yaw_deg_s_dt": 5,      # ひねりイベント
    "d_ay_g_s_dt": 5,
}

# 外れ値クリップ
CLIP_LO_Q = 0.05
CLIP_HI_Q = 0.95

# robust正規化後クリップ
ROBUST_CLIP = 2.0

# intro_event しきい値
INTRO_EVENT_THRESHOLD = 0.60


# =========================================================
# ユーティリティ
# =========================================================
def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def find_section_csv(run_dir: Path, section_id: str) -> Path:
    """
    例:
      run_id = run_20260322_054454_699988
      対象ファイル = run_20260322_time_S1_timeseries.csv
    """
    prefix = "_".join(run_dir.name.split("_")[:2])  # run_20260322
    target = run_dir / f"{prefix}_time_{section_id}_timeseries.csv"
    if not target.exists():
        raise FileNotFoundError(f"対象CSVが見つかりません: {target}")
    return target


def check_columns(df: pd.DataFrame, required: Iterable[str]) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"必須列が不足しています: {missing}")


def interpolate_series(s: pd.Series) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce")
    s = s.interpolate(method="linear", limit_direction="both")
    s = s.bfill().ffill()
    return s


def winsorize_series(s: pd.Series, q_low: float, q_high: float) -> pd.Series:
    valid = s.dropna()
    if len(valid) == 0:
        return s.copy()
    lo = valid.quantile(q_low)
    hi = valid.quantile(q_high)
    return s.clip(lower=lo, upper=hi)


def smooth_series(s: pd.Series, window: int) -> pd.Series:
    if window <= 1:
        return s.copy()
    return s.rolling(window=window, center=True, min_periods=1).mean()


def robust_normalize_series(s: pd.Series, clip_abs: float = 2.0) -> pd.Series:
    """
    median/IQR で正規化し、[-clip_abs, clip_abs]にクリップ後、[-1,1]にスケール
    """
    valid = s.dropna()
    if len(valid) == 0:
        return pd.Series(np.zeros(len(s)), index=s.index, dtype=float)

    med = valid.median()
    q1 = valid.quantile(0.25)
    q3 = valid.quantile(0.75)
    iqr = q3 - q1

    if pd.isna(iqr) or abs(iqr) < 1e-12:
        out = s - med
        max_abs = out.abs().max()
        if pd.isna(max_abs) or max_abs < 1e-12:
            return pd.Series(np.zeros(len(s)), index=s.index, dtype=float)
        return (out / max_abs).fillna(0.0)

    z = (s - med) / iqr
    z = z.clip(-clip_abs, clip_abs)
    z = z / clip_abs
    return z.fillna(0.0)


def to_01_from_norm(s_norm: pd.Series) -> pd.Series:
    """
    [-1,1] -> [0,1]
    """
    return ((s_norm + 1.0) / 2.0).clip(0.0, 1.0)


def clip_pm1(series: pd.Series) -> pd.Series:
    return series.clip(-1.0, 1.0)


def clip_01(series: pd.Series) -> pd.Series:
    return series.clip(0.0, 1.0)


# =========================================================
# メイン処理
# =========================================================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="R18 S1時系列CSVから必要列を抽出し、補間・平滑化・規格化して色付け用制御信号を作る"
    )
    parser.add_argument(
        "--base-dir",
        type=str,
        default=DEFAULT_BASE_DIR,
        help="by_run の親ディレクトリ",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=DEFAULT_RUN_ID,
        help="run ID",
    )
    parser.add_argument(
        "--section",
        type=str,
        default=DEFAULT_SECTION,
        help="対象セクションID（例: S1）",
    )
    parser.add_argument(
        "--include-optional",
        action="store_true",
        help="任意列も含めて出力する",
    )
    args = parser.parse_args()

    base_dir = Path(args.base_dir)
    run_dir = base_dir / args.run_id

    if not run_dir.exists():
        raise FileNotFoundError(f"run_dir が存在しません: {run_dir}")

    in_csv = find_section_csv(run_dir, args.section)
    out_dir = run_dir / "preprocessed_for_coloring"
    ensure_dir(out_dir)

    df = pd.read_csv(in_csv)
    check_columns(df, REQUIRED_COLUMNS)

    target_cols = REQUIRED_COLUMNS[:]
    if args.include_optional:
        for c in OPTIONAL_COLUMNS:
            if c in df.columns:
                target_cols.append(c)

    target_cols = list(dict.fromkeys(target_cols))

    work = df[target_cols].copy()

    for c in work.columns:
        work[c] = pd.to_numeric(work[c], errors="coerce")

    out = pd.DataFrame()
    out["t_rel_sec"] = work["t_rel_sec"]

    feature_cols = [c for c in target_cols if c != "t_rel_sec"]

    for col in feature_cols:
        raw = work[col].copy()
        interp = interpolate_series(raw)
        clipped = winsorize_series(interp, CLIP_LO_Q, CLIP_HI_Q)
        smoothed = smooth_series(clipped, window=SMOOTH_WINDOWS.get(col, 5))
        norm = robust_normalize_series(smoothed, clip_abs=ROBUST_CLIP)

        out[f"{col}_raw"] = raw
        out[f"{col}_interp"] = interp
        out[f"{col}_clip"] = clipped
        out[f"{col}_sm"] = smoothed
        out[f"{col}_norm"] = norm

    # =====================================================
    # S1専用 制御信号（R18版）
    # =====================================================
    # 導入の呼吸包絡:
    # S1はK1600GT版同様、d_speed主体を維持
    out["intro_breath"] = out["d_speed_kmh_dt_norm"]

    # 局所アクセント:
    # ax主体 + ayを少量加えて、R18の横方向の張りを反映
    accent_src = (
        0.80 * to_01_from_norm(out["ax_g_s_norm"])
        + 0.20 * out["ay_g_s_norm"].abs()
    )
    out["accent_strength"] = clip_01(accent_src)

    # 導入の陰影:
    # -pitch主体 + yawを少量加えて、車体の塊感を陰影に反映
    shadow_src = (
        0.75 * (-out["pitch_deg_s_norm"])
        + 0.25 * out["yaw_deg_s_norm"]
    )
    out["shadow_shape"] = clip_pm1(shadow_src)

    # 微小イベント:
    # |d_pitch|主体 + |d_yaw|を少量加えて、ひねりの立ち上がりも反映
    event_src = (
        0.75 * out["d_pitch_deg_s_dt_norm"].abs()
        + 0.25 * out["d_yaw_deg_s_dt_norm"].abs()
    )
    out["intro_event_strength"] = clip_01(event_src)
    out["intro_event"] = (
        out["intro_event_strength"] >= INTRO_EVENT_THRESHOLD
    ).astype(int)

    # 補助列
    out["curve_hint"] = out["yaw_deg_s_norm"]
    out["curve_event_hint"] = out["d_yaw_deg_s_dt_norm"].abs().clip(0.0, 1.0)
    out["lateral_hint"] = out["ay_g_s_norm"].abs().clip(0.0, 1.0)

    if "d_ay_g_s_dt_norm" in out.columns:
        out["lateral_event_hint"] = out["d_ay_g_s_dt_norm"].abs().clip(0.0, 1.0)

    # =====================================================
    # メタ情報
    # =====================================================
    meta_rows = []
    for col in feature_cols:
        series = pd.to_numeric(work[col], errors="coerce")
        valid = series.dropna()

        if len(valid) == 0:
            meta_rows.append(
                {
                    "column": col,
                    "n_valid": 0,
                    "median_raw": np.nan,
                    "q05_raw": np.nan,
                    "q95_raw": np.nan,
                    "smooth_window": SMOOTH_WINDOWS.get(col, 5),
                    "normalized_to": "[-1,1]",
                }
            )
            continue

        meta_rows.append(
            {
                "column": col,
                "n_valid": int(len(valid)),
                "median_raw": float(valid.median()),
                "q05_raw": float(valid.quantile(CLIP_LO_Q)),
                "q95_raw": float(valid.quantile(CLIP_HI_Q)),
                "smooth_window": SMOOTH_WINDOWS.get(col, 5),
                "normalized_to": "[-1,1]",
            }
        )

    meta_df = pd.DataFrame(meta_rows)

    prefix = "_".join(args.run_id.split("_")[:2])  # run_20260322
    out_csv = out_dir / f"{prefix}_time_{args.section}_preprocessed_for_coloring.csv"
    meta_csv = out_dir / f"{prefix}_time_{args.section}_preprocess_metadata.csv"

    out.to_csv(out_csv, index=False, encoding="utf-8-sig")
    meta_df.to_csv(meta_csv, index=False, encoding="utf-8-sig")

    print(f"[OK] input : {in_csv}")
    print(f"[OK] output: {out_csv}")
    print(f"[OK] meta  : {meta_csv}")
    print(f"[INFO] columns used: {target_cols}")
    print(f"[INFO] rows: {len(out)}")
    print(f"[INFO] intro_event threshold: {INTRO_EVENT_THRESHOLD}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())