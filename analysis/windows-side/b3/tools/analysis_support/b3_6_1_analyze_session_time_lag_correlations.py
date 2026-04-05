# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import math
import re
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


# =========================================================
# 設定
# =========================================================
DEFAULT_BASE_DIR = r"D:\701lab\work\phaseB\analysis\b3\session_timeseries\by_run"
DEFAULT_RUN_ID = "run_20260308_060029_104785"

# 列名抽出条件：
# 基本は末尾が _s または _s_dt
# ただし d_speed_kmh_dt も明示的に追加対象にする
TARGET_COL_PATTERN = re.compile(r".*(_s|_s_dt)$")
EXTRA_TARGET_COLUMNS = {
    "d_speed_kmh_dt",
}

# セッションファイル名：
# 例: run_20260308_time_S5_timeseries.csv
SESSION_FILE_PATTERN = re.compile(r"^(?P<prefix>.+)_time_S(?P<sid>[1-6])_timeseries\.csv$")

# 時間列候補
TIME_COLUMN_CANDIDATES = [
    "elapsed_s",
    "time_s",
    "t_s",
    "sec",
    "seconds",
    "rel_time_s",
    "t_rel_s",
    "timestamp_s",
]


# =========================================================
# ユーティリティ
# =========================================================
def find_session_csvs(run_dir: Path) -> list[tuple[str, Path]]:
    """
    run_dir 直下から session csv を探し、
    [("S1", path1), ("S2", path2), ...] の形で返す
    """
    out = []

    for p in sorted(run_dir.glob("*_time_S*_timeseries.csv")):
        m = SESSION_FILE_PATTERN.match(p.name)
        if m is None:
            continue
        sid = f"S{m.group('sid')}"
        out.append((sid, p))

    out.sort(key=lambda x: int(x[0][1:]))
    return out


def is_target_column(col_name: str) -> bool:
    """
    相関対象列かどうかを判定
    """
    if col_name in EXTRA_TARGET_COLUMNS:
        return True
    if TARGET_COL_PATTERN.match(col_name) is not None:
        return True
    return False


def pick_target_columns(df: pd.DataFrame) -> list[str]:
    """
    _s / _s_dt で終わる数値列＋明示追加列を抽出
    """
    cols = []
    for c in df.columns:
        if not is_target_column(c):
            continue
        if pd.api.types.is_numeric_dtype(df[c]):
            cols.append(c)
    return cols


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def sanitize_filename(text: str) -> str:
    """
    ファイル名に使えない文字を置換
    """
    return re.sub(r'[\\/:*?"<>|]+', "_", text)


def estimate_dt_seconds(df: pd.DataFrame, explicit_time_col: str | None = None) -> tuple[float, str]:
    """
    時間列からサンプリング間隔[sec]を推定する。
    見つからない場合は 1.0 sec/sample とする。
    """
    if explicit_time_col is not None and explicit_time_col in df.columns:
        candidates = [explicit_time_col]
    else:
        candidates = [c for c in TIME_COLUMN_CANDIDATES if c in df.columns]

    for c in candidates:
        s = pd.to_numeric(df[c], errors="coerce").dropna()
        if len(s) < 3:
            continue
        ds = np.diff(s.values)
        ds = ds[np.isfinite(ds)]
        ds = ds[ds > 0]
        if len(ds) == 0:
            continue
        dt = float(np.median(ds))
        if dt > 0:
            return dt, c

    return 1.0, "ROW_INDEX_ASSUMED_1SEC"


def filter_valid_columns(sub: pd.DataFrame, min_rows: int) -> list[str]:
    """
    全部NaNや定数列を除外
    """
    valid_cols = []
    for c in sub.columns:
        series = sub[c].dropna()
        if len(series) < min_rows:
            continue
        if series.nunique() <= 1:
            continue
        valid_cols.append(c)
    return valid_cols


def compute_lagged_corr_one_pair(
    x: pd.Series,
    y: pd.Series,
    dt_sec: float,
    max_lag_sec: float,
    min_overlap_rows: int,
    method: str,
) -> pd.DataFrame:
    """
    1ペアについて、±max_lag_sec のラグ相関を計算する

    定義:
      lag_sec > 0 のとき、
      corr( x(t), y(t + lag_sec) ) を見る
    実装上は y を -lag_steps シフトして x と揃える
    """
    if method not in {"pearson", "spearman"}:
        raise ValueError("method must be 'pearson' or 'spearman'")

    max_lag_steps = int(round(max_lag_sec / dt_sec))
    rows = []

    for lag_steps in range(-max_lag_steps, max_lag_steps + 1):
        y_shifted = y.shift(-lag_steps)

        pair = pd.DataFrame({"x": x, "y": y_shifted}).dropna()
        n_overlap = len(pair)

        if n_overlap < min_overlap_rows:
            corr_val = np.nan
        else:
            corr_val = pair["x"].corr(pair["y"], method=method)

        rows.append(
            {
                "lag_steps": lag_steps,
                "lag_sec": lag_steps * dt_sec,
                "corr": corr_val,
                "abs_corr": np.nan if pd.isna(corr_val) else abs(corr_val),
                "n_overlap": n_overlap,
            }
        )

    out = pd.DataFrame(rows)
    return out


def save_lag_curve_plot(
    lag_df: pd.DataFrame,
    out_png: Path,
    title: str,
) -> None:
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(lag_df["lag_sec"], lag_df["corr"], marker="o", markersize=3)
    ax.axhline(0.0, linewidth=1)
    ax.axvline(0.0, linewidth=1, linestyle="--")
    ax.set_xlabel("Lag [sec]")
    ax.set_ylabel("Correlation")
    ax.set_ylim(-1.05, 1.05)
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def summarize_best_lag(
    pair_name_1: str,
    pair_name_2: str,
    lag_df: pd.DataFrame,
) -> dict:
    valid = lag_df.dropna(subset=["corr"]).copy()
    if len(valid) == 0:
        return {
            "var1": pair_name_1,
            "var2": pair_name_2,
            "best_lag_sec_abs": np.nan,
            "best_lag_steps_abs": np.nan,
            "best_corr_abs_signed": np.nan,
            "best_abs_corr": np.nan,
            "n_overlap_at_best_abs": np.nan,
            "best_lag_sec_pos": np.nan,
            "best_lag_steps_pos": np.nan,
            "best_corr_pos": np.nan,
            "n_overlap_at_best_pos": np.nan,
            "best_lag_sec_neg": np.nan,
            "best_lag_steps_neg": np.nan,
            "best_corr_neg": np.nan,
            "n_overlap_at_best_neg": np.nan,
        }

    # |corr| 最大
    i_abs = valid["abs_corr"].idxmax()
    r_abs = valid.loc[i_abs]

    # 正相関 最大
    pos = valid[valid["corr"] >= 0]
    if len(pos) > 0:
        i_pos = pos["corr"].idxmax()
        r_pos = pos.loc[i_pos]
        best_lag_sec_pos = r_pos["lag_sec"]
        best_lag_steps_pos = r_pos["lag_steps"]
        best_corr_pos = r_pos["corr"]
        n_overlap_at_best_pos = r_pos["n_overlap"]
    else:
        best_lag_sec_pos = np.nan
        best_lag_steps_pos = np.nan
        best_corr_pos = np.nan
        n_overlap_at_best_pos = np.nan

    # 負相関 最小
    neg = valid[valid["corr"] <= 0]
    if len(neg) > 0:
        i_neg = neg["corr"].idxmin()
        r_neg = neg.loc[i_neg]
        best_lag_sec_neg = r_neg["lag_sec"]
        best_lag_steps_neg = r_neg["lag_steps"]
        best_corr_neg = r_neg["corr"]
        n_overlap_at_best_neg = r_neg["n_overlap"]
    else:
        best_lag_sec_neg = np.nan
        best_lag_steps_neg = np.nan
        best_corr_neg = np.nan
        n_overlap_at_best_neg = np.nan

    return {
        "var1": pair_name_1,
        "var2": pair_name_2,
        "best_lag_sec_abs": r_abs["lag_sec"],
        "best_lag_steps_abs": r_abs["lag_steps"],
        "best_corr_abs_signed": r_abs["corr"],
        "best_abs_corr": r_abs["abs_corr"],
        "n_overlap_at_best_abs": r_abs["n_overlap"],
        "best_lag_sec_pos": best_lag_sec_pos,
        "best_lag_steps_pos": best_lag_steps_pos,
        "best_corr_pos": best_corr_pos,
        "n_overlap_at_best_pos": n_overlap_at_best_pos,
        "best_lag_sec_neg": best_lag_sec_neg,
        "best_lag_steps_neg": best_lag_steps_neg,
        "best_corr_neg": best_corr_neg,
        "n_overlap_at_best_neg": n_overlap_at_best_neg,
    }


def write_session_info(
    out_txt: Path,
    sid: str,
    csv_path: Path,
    dt_sec: float,
    time_col_used: str,
    n_rows: int,
    n_cols: int,
    used_cols: list[str],
    method: str,
    max_lag_sec: float,
) -> None:
    with open(out_txt, "w", encoding="utf-8") as f:
        f.write(f"session_id      : {sid}\n")
        f.write(f"source_csv      : {csv_path}\n")
        f.write(f"method          : {method}\n")
        f.write(f"time_col_used   : {time_col_used}\n")
        f.write(f"estimated_dt_s  : {dt_sec}\n")
        f.write(f"max_lag_sec     : {max_lag_sec}\n")
        f.write(f"n_rows          : {n_rows}\n")
        f.write(f"n_cols          : {n_cols}\n")
        f.write("\n[used_columns]\n")
        for c in used_cols:
            f.write(c + "\n")


# =========================================================
# メイン処理
# =========================================================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="session_timeseries CSV から区間ごとに各変数ペアの ±lag 秒ラグ相関を計算する"
    )
    parser.add_argument(
        "--base-dir",
        type=str,
        default=DEFAULT_BASE_DIR,
        help="by_run ディレクトリの親パス",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=DEFAULT_RUN_ID,
        help="run ID（例: run_20260308_060029_104785）",
    )
    parser.add_argument(
        "--method",
        type=str,
        default="pearson",
        choices=["pearson", "spearman"],
        help="相関係数の種類",
    )
    parser.add_argument(
        "--dropna",
        action="store_true",
        help="対象列に NaN が含まれる行を最初に丸ごと削除してから処理する",
    )
    parser.add_argument(
        "--min-rows",
        type=int,
        default=5,
        help="列の有効判定に必要な最小行数",
    )
    parser.add_argument(
        "--min-overlap-rows",
        type=int,
        default=5,
        help="各ラグ相関を計算するために必要な最小重なり行数",
    )
    parser.add_argument(
        "--max-lag-sec",
        type=float,
        default=20.0,
        help="ラグ相関の最大シフト秒数（±で計算）",
    )
    parser.add_argument(
        "--time-col",
        type=str,
        default=None,
        help="時間列名を明示指定したい場合に指定",
    )
    args = parser.parse_args()

    base_dir = Path(args.base_dir)
    run_dir = base_dir / args.run_id

    if not run_dir.exists():
        raise FileNotFoundError(f"run_dir が存在しません: {run_dir}")

    session_files = find_session_csvs(run_dir)
    if not session_files:
        raise FileNotFoundError(f"セッションCSVが見つかりません: {run_dir}")

    out_root = run_dir / f"lagcorr_{args.method}_pm{int(args.max_lag_sec)}s"
    ensure_dir(out_root)

    print(f"[INFO] run_dir   : {run_dir}")
    print(f"[INFO] out_root  : {out_root}")
    print(f"[INFO] method    : {args.method}")
    print(f"[INFO] dropna    : {args.dropna}")
    print(f"[INFO] max_lag_s : {args.max_lag_sec}")
    print(f"[INFO] sessions  : {[sid for sid, _ in session_files]}")

    for sid, csv_path in session_files:
        print(f"\n[INFO] reading: {csv_path.name}")
        df = pd.read_csv(csv_path)

        target_cols = pick_target_columns(df)
        if not target_cols:
            print(f"[WARN] {sid}: 対象列が見つかりません")
            continue

        sub = df[target_cols].copy()

        # 数値変換（念のため）
        for c in sub.columns:
            sub[c] = pd.to_numeric(sub[c], errors="coerce")

        if args.dropna:
            sub = sub.dropna(axis=0, how="any")

        valid_cols = filter_valid_columns(sub, min_rows=args.min_rows)
        sub = sub[valid_cols]

        if sub.shape[1] < 2:
            print(f"[WARN] {sid}: 相関計算に必要な有効列が2本未満です")
            continue
        if sub.shape[0] < args.min_rows:
            print(f"[WARN] {sid}: 有効行数が不足しています")
            continue

        dt_sec, time_col_used = estimate_dt_seconds(df, explicit_time_col=args.time_col)
        max_lag_steps = int(round(args.max_lag_sec / dt_sec))

        session_dir = out_root / sid
        pair_csv_dir = session_dir / "pair_csv"
        pair_png_dir = session_dir / "pair_png"
        ensure_dir(session_dir)
        ensure_dir(pair_csv_dir)
        ensure_dir(pair_png_dir)

        print(f"[INFO] {sid}: dt_sec={dt_sec:.6g}, time_col={time_col_used}, max_lag_steps={max_lag_steps}")
        print(f"[INFO] {sid}: rows={len(sub)}, cols={len(sub.columns)}")

        summary_rows = []

        for var1, var2 in combinations(sub.columns, 2):
            lag_df = compute_lagged_corr_one_pair(
                x=sub[var1],
                y=sub[var2],
                dt_sec=dt_sec,
                max_lag_sec=args.max_lag_sec,
                min_overlap_rows=args.min_overlap_rows,
                method=args.method,
            )

            safe_name = sanitize_filename(f"{var1}__vs__{var2}")
            out_csv = pair_csv_dir / f"{safe_name}_lagcorr.csv"
            out_png = pair_png_dir / f"{safe_name}_lagcorr.png"

            lag_df.to_csv(out_csv, index=False, encoding="utf-8-sig")
            save_lag_curve_plot(
                lag_df,
                out_png,
                title=f"{sid}: {var1} vs {var2} ({args.method})",
            )

            summary_rows.append(summarize_best_lag(var1, var2, lag_df))

        summary_df = pd.DataFrame(summary_rows)
        if len(summary_df) > 0:
            summary_df = summary_df.sort_values(
                ["best_abs_corr", "best_corr_abs_signed"],
                ascending=[False, False]
            ).reset_index(drop=True)

        summary_csv = session_dir / f"{args.run_id}_{sid}_lagcorr_summary.csv"
        cols_txt = session_dir / f"{args.run_id}_{sid}_used_columns.txt"
        info_txt = session_dir / f"{args.run_id}_{sid}_info.txt"

        summary_df.to_csv(summary_csv, index=False, encoding="utf-8-sig")

        with open(cols_txt, "w", encoding="utf-8") as f:
            for c in sub.columns:
                f.write(c + "\n")

        write_session_info(
            out_txt=info_txt,
            sid=sid,
            csv_path=csv_path,
            dt_sec=dt_sec,
            time_col_used=time_col_used,
            n_rows=len(sub),
            n_cols=len(sub.columns),
            used_cols=list(sub.columns),
            method=args.method,
            max_lag_sec=args.max_lag_sec,
        )

        print(f"[OK] {sid}: saved summary -> {summary_csv.name}")
        print(f"[OK] {sid}: pair csv dir  -> {pair_csv_dir}")
        print(f"[OK] {sid}: pair png dir  -> {pair_png_dir}")

    print("\n[DONE]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())