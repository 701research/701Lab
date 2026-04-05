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
DEFAULT_RUN_ID = "run_20260308_060029_104785"
DEFAULT_SECTION = "S3"

# 今回の議論で使う列
REQUIRED_COLUMNS = [
    "t_rel_sec",
    "pitch_deg_s",
    "d_pitch_deg_s_dt",
    "ax_g_s",
    "d_speed_kmh_dt",
]

# 任意で残しておく列（必要なら将来使える）
OPTIONAL_COLUMNS = [
    "yaw_deg_s",
    "d_yaw_deg_s_dt",
]

# 平滑化窓
SMOOTH_WINDOWS = {
    "pitch_deg_s": 7,
    "d_pitch_deg_s_dt": 5,
    "ax_g_s": 3,
    "d_speed_kmh_dt": 9,
    "yaw_deg_s": 7,
    "d_yaw_deg_s_dt": 5,
}

# 外れ値クリップ用
CLIP_LO_Q = 0.05
CLIP_HI_Q = 0.95

# robust正規化後のクリップ範囲
ROBUST_CLIP = 2.0


# =========================================================
# ユーティリティ
# =========================================================
def find_section_csv(run_dir: Path, section_id: str) -> Path:
    """
    例:
      run_id = run_20260308_060029_104785
      対象ファイル = run_20260308_time_S3_timeseries.csv
    """
    prefix = "_".join(run_dir.name.split("_")[:2])  # run_20260308
    target = run_dir / f"{prefix}_time_{section_id}_timeseries.csv"
    if not target.exists():
        raise FileNotFoundError(f"対象CSVが見つかりません: {target}")
    return target


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def interpolate_series(s: pd.Series) -> pd.Series:
    """
    欠損補間:
    - 内部: 線形補間
    - 端点: 前後埋め
    """
    s = pd.to_numeric(s, errors="coerce")
    s = s.interpolate(method="linear", limit_direction="both")
    s = s.bfill().ffill()
    return s


def winsorize_series(s: pd.Series, q_low: float, q_high: float) -> pd.Series:
    """
    分位点でクリップ
    """
    valid = s.dropna()
    if len(valid) == 0:
        return s.copy()

    lo = valid.quantile(q_low)
    hi = valid.quantile(q_high)
    return s.clip(lower=lo, upper=hi)


def smooth_series(s: pd.Series, window: int) -> pd.Series:
    """
    centered moving average
    """
    if window <= 1:
        return s.copy()
    return s.rolling(window=window, center=True, min_periods=1).mean()


def robust_normalize_series(s: pd.Series, clip_abs: float = 2.0) -> pd.Series:
    """
    robust正規化:
    z = (x - median) / IQR
    その後 [-clip_abs, clip_abs] にクリップし、
    最終的に [-1, 1] にスケール
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


def to_centered_01(s_norm: pd.Series) -> pd.Series:
    """
    [-1, 1] -> [0, 1]
    event系などで使いたいとき用
    """
    return ((s_norm + 1.0) / 2.0).clip(0.0, 1.0)


def check_columns(df: pd.DataFrame, required: Iterable[str]) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"必須列が不足しています: {missing}")


# =========================================================
# メイン処理
# =========================================================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="S3時系列CSVから必要列を抽出し、補間・平滑化・規格化して保存する"
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
        help="対象セクションID（例: S3）",
    )
    parser.add_argument(
        "--include-optional",
        action="store_true",
        help="yaw系の任意列も含めて出力する",
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

    # 重複除去
    target_cols = list(dict.fromkeys(target_cols))

    work = df[target_cols].copy()

    # 念のため数値化
    for c in work.columns:
        work[c] = pd.to_numeric(work[c], errors="coerce")

    # 時間列はそのまま保持
    out = pd.DataFrame()
    out["t_rel_sec"] = work["t_rel_sec"]

    # 元列、補間列、クリップ列、平滑列、正規化列を順に作成
    feature_cols = [c for c in target_cols if c != "t_rel_sec"]

    for col in feature_cols:
        raw = work[col].copy()
        interp = interpolate_series(raw)
        clipped = winsorize_series(interp, CLIP_LO_Q, CLIP_HI_Q)

        window = SMOOTH_WINDOWS.get(col, 5)
        smoothed = smooth_series(clipped, window=window)

        norm = robust_normalize_series(smoothed, clip_abs=ROBUST_CLIP)

        out[f"{col}_raw"] = raw
        out[f"{col}_interp"] = interp
        out[f"{col}_clip"] = clipped
        out[f"{col}_sm"] = smoothed
        out[f"{col}_norm"] = norm

    # 今後の色付けで使いやすい別名も追加
    # S3用の主役4本
    out["melody_arc"] = out["pitch_deg_s_norm"]
    out["melody_event_strength"] = out["d_pitch_deg_s_dt_norm"].abs().clip(0.0, 1.0)
    out["accent_strength"] = to_centered_01(out["ax_g_s_norm"])
    out["phrase_drive"] = out["d_speed_kmh_dt_norm"]

    # melody_event の2値版も追加
    EVENT_THRESHOLD = 0.65
    out["melody_event"] = (out["melody_event_strength"] >= EVENT_THRESHOLD).astype(int)

    # メタ情報保存用
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

    prefix = "_".join(args.run_id.split("_")[:2])  # run_20260308
    out_csv = out_dir / f"{prefix}_time_{args.section}_preprocessed_for_coloring.csv"
    meta_csv = out_dir / f"{prefix}_time_{args.section}_preprocess_metadata.csv"

    out.to_csv(out_csv, index=False, encoding="utf-8-sig")
    meta_df.to_csv(meta_csv, index=False, encoding="utf-8-sig")

    print(f"[OK] input : {in_csv}")
    print(f"[OK] output: {out_csv}")
    print(f"[OK] meta  : {meta_csv}")
    print(f"[INFO] columns used: {target_cols}")
    print(f"[INFO] rows: {len(out)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())