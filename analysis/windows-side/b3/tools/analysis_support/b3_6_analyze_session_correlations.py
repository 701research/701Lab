# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import re
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

    # S1, S2, ... の順にソート
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


def save_corr_heatmap(
    corr: pd.DataFrame,
    out_png: Path,
    title: str,
    figsize_scale: float = 0.75,
) -> None:
    """
    相関行列のヒートマップを保存
    """
    n = max(4, len(corr.columns))
    fig_w = max(8, n * figsize_scale)
    fig_h = max(6, n * figsize_scale)

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    im = ax.imshow(corr.values, vmin=-1.0, vmax=1.0, aspect="auto")

    ax.set_title(title, fontsize=14)
    ax.set_xticks(np.arange(len(corr.columns)))
    ax.set_yticks(np.arange(len(corr.index)))
    ax.set_xticklabels(corr.columns, rotation=90, fontsize=9)
    ax.set_yticklabels(corr.index, fontsize=9)

    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Correlation", rotation=90)

    # 値を書き込む（列数が多すぎる場合は省略）
    if len(corr.columns) <= 16:
        for i in range(corr.shape[0]):
            for j in range(corr.shape[1]):
                v = corr.iat[i, j]
                ax.text(
                    j, i, f"{v:.2f}",
                    ha="center", va="center",
                    fontsize=8,
                    color="white" if abs(v) > 0.5 else "black"
                )

    fig.tight_layout()
    fig.savefig(out_png, dpi=200, bbox_inches="tight")
    plt.close(fig)


def build_pair_list(corr: pd.DataFrame) -> pd.DataFrame:
    """
    相関行列から、重複なしのペア一覧を作る
    """
    rows = []
    cols = list(corr.columns)

    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            c1 = cols[i]
            c2 = cols[j]
            r = corr.loc[c1, c2]
            rows.append(
                {
                    "var1": c1,
                    "var2": c2,
                    "corr": float(r),
                    "abs_corr": float(abs(r)),
                }
            )

    out = pd.DataFrame(rows)
    if len(out) > 0:
        out = out.sort_values(["abs_corr", "corr"], ascending=[False, False]).reset_index(drop=True)
    return out


def compute_corr(df: pd.DataFrame, method: str) -> pd.DataFrame:
    """
    相関行列を計算
    method: pearson / spearman
    """
    return df.corr(method=method)


# =========================================================
# メイン処理
# =========================================================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="session_timeseries CSV から _s / _s_dt 列と d_speed_kmh_dt の相関を計算する"
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
        help="対象列に NaN が含まれる行を丸ごと削除してから相関計算する",
    )
    parser.add_argument(
        "--min-rows",
        type=int,
        default=5,
        help="相関計算に必要な最小行数",
    )
    parser.add_argument(
        "--save-merged",
        action="store_true",
        help="全セッション結合版の相関も保存する",
    )
    args = parser.parse_args()

    base_dir = Path(args.base_dir)
    run_dir = base_dir / args.run_id

    if not run_dir.exists():
        raise FileNotFoundError(f"run_dir が存在しません: {run_dir}")

    session_files = find_session_csvs(run_dir)
    if not session_files:
        raise FileNotFoundError(f"セッションCSVが見つかりません: {run_dir}")

    out_dir = run_dir / f"correlation_{args.method}"
    ensure_dir(out_dir)

    print(f"[INFO] run_dir   : {run_dir}")
    print(f"[INFO] out_dir   : {out_dir}")
    print(f"[INFO] method    : {args.method}")
    print(f"[INFO] dropna    : {args.dropna}")
    print(f"[INFO] sessions  : {[sid for sid, _ in session_files]}")
    print(f"[INFO] extra target columns : {sorted(EXTRA_TARGET_COLUMNS)}")

    merged_list = []

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

        # 全部NaNや定数列を除外
        valid_cols = []
        for c in sub.columns:
            series = sub[c].dropna()
            if len(series) < args.min_rows:
                continue
            if series.nunique() <= 1:
                continue
            valid_cols.append(c)

        sub = sub[valid_cols]

        if sub.shape[1] < 2:
            print(f"[WARN] {sid}: 相関計算に必要な有効列が2本未満です")
            continue
        if sub.shape[0] < args.min_rows:
            print(f"[WARN] {sid}: 有効行数が不足しています")
            continue

        corr = compute_corr(sub, args.method)

        corr_csv = out_dir / f"{args.run_id}_{sid}_corr_matrix.csv"
        pairs_csv = out_dir / f"{args.run_id}_{sid}_corr_pairs_sorted.csv"
        heat_png = out_dir / f"{args.run_id}_{sid}_corr_heatmap.png"
        cols_txt = out_dir / f"{args.run_id}_{sid}_used_columns.txt"

        corr.to_csv(corr_csv, encoding="utf-8-sig")
        build_pair_list(corr).to_csv(pairs_csv, index=False, encoding="utf-8-sig")
        save_corr_heatmap(corr, heat_png, title=f"{args.run_id} {sid} correlation ({args.method})")

        with open(cols_txt, "w", encoding="utf-8") as f:
            for c in sub.columns:
                f.write(c + "\n")

        print(f"[OK] {sid}: rows={len(sub)}, cols={len(sub.columns)}")
        print(f"     used columns: {list(sub.columns)}")
        print(f"     saved: {corr_csv.name}")
        print(f"     saved: {pairs_csv.name}")
        print(f"     saved: {heat_png.name}")

        tmp = sub.copy()
        tmp["__session_id__"] = sid
        merged_list.append(tmp)

    # -----------------------------------------------------
    # 全セッション結合版
    # -----------------------------------------------------
    if args.save_merged and merged_list:
        merged = pd.concat(merged_list, axis=0, ignore_index=True)

        if "__session_id__" in merged.columns:
            merged = merged.drop(columns="__session_id__")

        # 列ごとの有効性再チェック
        valid_cols = []
        for c in merged.columns:
            series = merged[c].dropna()
            if len(series) < args.min_rows:
                continue
            if series.nunique() <= 1:
                continue
            valid_cols.append(c)

        merged = merged[valid_cols]

        if merged.shape[1] >= 2 and merged.shape[0] >= args.min_rows:
            corr = compute_corr(merged, args.method)

            corr_csv = out_dir / f"{args.run_id}_ALL_corr_matrix.csv"
            pairs_csv = out_dir / f"{args.run_id}_ALL_corr_pairs_sorted.csv"
            heat_png = out_dir / f"{args.run_id}_ALL_corr_heatmap.png"

            corr.to_csv(corr_csv, encoding="utf-8-sig")
            build_pair_list(corr).to_csv(pairs_csv, index=False, encoding="utf-8-sig")
            save_corr_heatmap(corr, heat_png, title=f"{args.run_id} ALL correlation ({args.method})")

            print(f"\n[OK] ALL: rows={len(merged)}, cols={len(merged.columns)}")
            print(f"     used columns: {list(merged.columns)}")
            print(f"     saved: {corr_csv.name}")
            print(f"     saved: {pairs_csv.name}")
            print(f"     saved: {heat_png.name}")
        else:
            print("\n[WARN] ALL: 結合後に有効列が不足し、相関を計算できません")

    print("\n[DONE]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())