# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import pandas as pd


# =========================================================
# 5要素の初版写像式
# =========================================================
def compute_music_controls(df: pd.DataFrame) -> pd.DataFrame:
    required_cols = [
        "run_id",
        "bike",
        "session_id",
        "session_name",
        "speed_n",
        "speed_var_n",
        "ax_n",
        "pitch_var_n",
        "hr_n",
        "ay_n",
    ]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"必要列が不足しています: {missing}")

    out = df.copy()

    # 初版写像式
    out["BPM"] = 60 + 35 * out["speed_n"] + 5 * out["hr_n"]

    out["note_density"] = (
        0.15
        + 0.55 * out["ax_n"]
        + 0.15 * out["speed_n"]
        + 0.10 * out["hr_n"]
    )

    out["phrase_span"] = (
        0.20
        + 0.60 * out["pitch_var_n"]
        + 0.15 * out["ax_n"]
    )

    out["harmonic_tension"] = (
        0.10
        + 0.55 * out["hr_n"]
        + 0.20 * out["speed_n"]
        + 0.10 * out["speed_var_n"]
    )

    out["inner_voice_swing"] = (
        0.05
        + 0.70 * out["ay_n"]
        + 0.10 * out["pitch_var_n"]
    )

    # 見やすさのため丸め列も追加
    out["BPM_r"] = out["BPM"].round(1)
    out["note_density_r"] = out["note_density"].round(3)
    out["phrase_span_r"] = out["phrase_span"].round(3)
    out["harmonic_tension_r"] = out["harmonic_tension"].round(3)
    out["inner_voice_swing_r"] = out["inner_voice_swing"].round(3)

    return out


# =========================================================
# 出力列の整理
# =========================================================
def make_output_table(df: pd.DataFrame) -> pd.DataFrame:
    preferred_cols = [
        "run_id",
        "bike",
        "session_id",
        "session_name",
        "duration_sec",
        "mean_speed_kmh",
        "std_speed_kmh",
        "mean_hr_bpm",
        "mean_rr_ms",
        "ax_event_rate",
        "std_pitch_deg",
        "ay_energy",
        "gx_energy",
        "speed_n",
        "speed_var_n",
        "ax_n",
        "pitch_var_n",
        "hr_n",
        "ay_n",
        "BPM",
        "note_density",
        "phrase_span",
        "harmonic_tension",
        "inner_voice_swing",
        "BPM_r",
        "note_density_r",
        "phrase_span_r",
        "harmonic_tension_r",
        "inner_voice_swing_r",
    ]

    cols = [c for c in preferred_cols if c in df.columns]
    return df[cols].copy()


# =========================================================
# 1ファイル処理
# =========================================================
def process_one_csv(csv_path: Path, overwrite: bool = True) -> Path:
    df = pd.read_csv(csv_path)
    out = compute_music_controls(df)
    out_table = make_output_table(out)

    out_path = csv_path.parent / "session_music_controls.csv"

    if out_path.exists() and not overwrite:
        raise FileExistsError(f"出力先が既に存在します: {out_path}")

    out_table.to_csv(out_path, index=False, encoding="utf-8-sig")
    return out_path


# =========================================================
# ルート配下を走査
# =========================================================
def find_target_csvs(root_dir: Path) -> list[Path]:
    """
    各 runID フォルダ内の *_session_features.csv を探す
    """
    candidates = sorted(root_dir.rglob("*_session_features.csv"))
    return [p for p in candidates if p.is_file()]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="各 runID フォルダの session_features CSV から 5要素制御値を計算して保存する"
    )
    parser.add_argument(
        "--root",
        type=str,
        default=r"D:\701lab\work\phaseB\analysis\b3\session_features\by_run",
        help="runID フォルダ群を含むルートフォルダ",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="既存の session_music_controls.csv を上書きしない",
    )
    args = parser.parse_args()

    root_dir = Path(args.root)
    overwrite = not args.no_overwrite

    if not root_dir.exists():
        print(f"[ERROR] ルートフォルダが存在しません: {root_dir}")
        return 1

    csv_files = find_target_csvs(root_dir)
    if not csv_files:
        print(f"[ERROR] 対象CSVが見つかりませんでした: {root_dir}")
        return 1

    print(f"[INFO] 対象CSV数: {len(csv_files)}")

    ok_count = 0
    ng_count = 0

    for csv_path in csv_files:
        try:
            out_path = process_one_csv(csv_path, overwrite=overwrite)
            print(f"[OK] {csv_path.name} -> {out_path}")
            ok_count += 1
        except Exception as e:
            print(f"[NG] {csv_path}: {e}")
            ng_count += 1

    print("-" * 60)
    print(f"[DONE] 成功: {ok_count}, 失敗: {ng_count}")

    return 0 if ng_count == 0 else 2


if __name__ == "__main__":
    sys.exit(main())