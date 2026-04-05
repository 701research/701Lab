# -*- coding: utf-8 -*-
from __future__ import annotations

import math
import subprocess
from pathlib import Path

import pretty_midi
import pandas as pd
import numpy as np


# =========================================================
# 基本設定
# =========================================================
BEATS_PER_BAR = 4

BASE_DIR = Path(__file__).resolve().parent
MIDI_OUT = (BASE_DIR / "k1600gt_701lab_v2_13_s1_balanced_phrase.mid").resolve()
WAV_OUT  = (BASE_DIR / "k1600gt_701lab_v2_13_s1_balanced_phrase.wav").resolve()

FLUIDSYNTH = Path(r"C:\fluidsynth\bin\fluidsynth.exe").resolve()
SOUNDFONT  = Path(r"C:\FluidR3_GM\FluidR3_GM.sf2").resolve()

# S1 前処理済みCSV
S1_CONTROL_CSV = Path(
    r"D:\701lab\work\phaseB\analysis\b3\session_timeseries\by_run"
    r"\run_20260308_060029_104785\preprocessed_for_coloring"
    r"\run_20260308_time_S1_preprocessed_for_coloring.csv"
).resolve()

# S2 前処理済みCSV
S2_CONTROL_CSV = Path(
    r"D:\701lab\work\phaseB\analysis\b3\session_timeseries\by_run"
    r"\run_20260308_060029_104785\preprocessed_for_coloring"
    r"\run_20260308_time_S2_preprocessed_for_coloring.csv"
).resolve()

# S3 前処理済みCSV
S3_CONTROL_CSV = Path(
    r"D:\701lab\work\phaseB\analysis\b3\session_timeseries\by_run"
    r"\run_20260308_060029_104785\preprocessed_for_coloring"
    r"\run_20260308_time_S3_preprocessed_for_coloring.csv"
).resolve()

# S5 前処理済みCSV
S5_CONTROL_CSV = Path(
    r"D:\701lab\work\phaseB\analysis\b3\session_timeseries\by_run"
    r"\run_20260308_060029_104785\preprocessed_for_coloring"
    r"\run_20260308_time_S5_preprocessed_for_coloring.csv"
).resolve()

# -----------------------------
# S1 色付けパラメータ
# -----------------------------
S1_PITCH_STEPS_MAX = 2
S1_VEL_GAIN_VN1 = 10
S1_VEL_GAIN_BASS = 3
S1_DUR_GAIN = 0.12
S1_EVENT_VEL_DROP = 5
S1_GRACE_RATIO = 0.20
S1_EVENT_THRESHOLD = 0.50
S1_MIN_EVENT_GAP_SEC = 0.35

# S1 左手うるささ対策
S1_HEAD_BOOST_2 = -18
S1_HEAD_MAP_4 = {0: -18, 2: -6}
S1_HEAD_MAP_8 = {0: -18, 4: -6}
S1_HEAD_REDUCE_BAR_LOCAL_1 = 0.18
S1_HEAD_REDUCE_BAR_LOCAL_2 = 0.36
S1_HEAD_REDUCE_VEL_1 = 12
S1_HEAD_REDUCE_VEL_2 = 6
S1_HEAD_SHORTEN_RATIO = 0.55

# -----------------------------
# S2 色付けパラメータ
# -----------------------------
S2_PITCH_STEPS_MAX = 2
S2_VEL_GAIN_VN1 = 10
S2_VEL_GAIN_BASS = 8
S2_DUR_GAIN = 0.12
S2_EVENT_VEL_DROP = 8
S2_GRACE_RATIO = 0.16
S2_EVENT_THRESHOLD = 0.55
S2_MIN_EVENT_GAP_SEC = 0.40

# -----------------------------
# S3 色付けパラメータ
# -----------------------------
S3_PITCH_STEPS_MAX = 3
S3_VEL_GAIN_VN1 = 16
S3_VEL_GAIN_BASS = 14
S3_DUR_GAIN = 0.22
S3_EVENT_VEL_DROP = 10
S3_GRACE_RATIO = 0.22
S3_EVENT_THRESHOLD = 0.35
S3_MIN_EVENT_GAP_SEC = 0.35

# -----------------------------
# S5 ボレロ色付けパラメータ
# -----------------------------
S5_SNARE_BASE_VEL = 54
S5_SNARE_ENV_GAIN = 14
S5_SNARE_ACCENT_GAIN = 14
S5_SNARE_VELOCITY_GAIN = 10
S5_BD_UNDERLAY_DROP = 22
S5_HH_DROP = 30

# 反復崩し用
S5_DENSITY_KEEP4_TH = 0.18
S5_DENSITY_KEEP3_TH = -0.12
S5_EVENT_THRESHOLD = 0.50
S5_EXTRA_HIT_DROP = 8

# yaw強調用
S5_YAW_STRONG_GAIN = 18
S5_YAW_PEAK_THRESHOLD = 0.55

# ドラムノート（GM）
DRUM_SNARE_MAIN = 38
DRUM_CLOSED_HH = 42
DRUM_BD_SUB = 36

# 追加: S1 / S3 用の控えめドラム
DRUM_SOFT_TOM = 45
DRUM_SOFT_HH = 42
DRUM_SOFT_KICK = 36


# =========================================================
# 便利関数
# =========================================================
def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def add_note(inst, pitch, start, end, vel):
    if end <= start:
        return
    inst.notes.append(
        pretty_midi.Note(
            velocity=int(clamp(round(vel), 1, 127)),
            pitch=int(round(pitch)),
            start=float(start),
            end=float(end),
        )
    )

def pseudo01(x: float) -> float:
    return 0.5 + 0.5 * math.sin(x * 12.345 + math.sin(x * 3.21))

def to_centered_from_01(x01: float) -> float:
    return clamp(2.0 * x01 - 1.0, -1.0, 1.0)

def apply_s1_piano_head_control(vel: float, st: float, bar_start: float, bar_dur: float, en: float):
    bar_local = (st - bar_start) / max(bar_dur, 1e-9)

    if bar_local < S1_HEAD_REDUCE_BAR_LOCAL_1:
        vel -= S1_HEAD_REDUCE_VEL_1
        en = st + (en - st) * S1_HEAD_SHORTEN_RATIO
    elif bar_local < S1_HEAD_REDUCE_BAR_LOCAL_2:
        vel -= S1_HEAD_REDUCE_VEL_2

    return vel, en

def thin_s1_bass_pattern(pat: list[int], u_bar: float = 0.0) -> list[tuple[int, int]]:
    n = len(pat)

    if u_bar >= 0.90:
        if n == 2:
            return [(0, pat[0]), (1, pat[1])]
        if n == 4:
            return [(1, pat[1]), (2, pat[2]), (3, pat[3])]
        if n >= 8:
            return [(2, pat[2]), (4, pat[4]), (6, pat[6])]

    if n == 2:
        return [(1, pat[1])]
    if n == 4:
        return [(1, pat[1]), (3, pat[3])]
    if n >= 8:
        return [(3, pat[3]), (6, pat[6])]

    return list(enumerate(pat))

def thin_s1_chord_tones(triad: list[int], u_bar: float) -> list[int]:
    triad_sorted = sorted(triad)

    if u_bar < 0.50:
        return [triad_sorted[1], triad_sorted[2]]
    if u_bar < 0.75:
        return [triad_sorted[0], triad_sorted[2]]
    return triad_sorted


# =========================================================
# 制御データ読み込み
# =========================================================
def _interp_control(arr_u: np.ndarray, arr_y: np.ndarray, u: float) -> float:
    u = float(clamp(u, 0.0, 1.0))
    return float(np.interp(u, arr_u, arr_y))

def _load_control_csv(csv_path: Path, required_cols: list[str]) -> dict:
    if not csv_path.exists():
        raise FileNotFoundError(f"control CSV not found: {csv_path}")

    df = pd.read_csv(csv_path)
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise KeyError(f"control CSV missing columns: {missing}")

    t = pd.to_numeric(df["t_rel_sec"], errors="coerce").to_numpy(dtype=float)
    mask = np.isfinite(t)
    if mask.sum() < 2:
        raise RuntimeError(f"insufficient valid t_rel_sec values: {csv_path}")

    data = {"t_rel_sec": t[mask]}
    for c in required_cols:
        if c == "t_rel_sec":
            continue
        arr = pd.to_numeric(df[c], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        data[c] = arr[mask]

    order = np.argsort(data["t_rel_sec"])
    for k in list(data.keys()):
        data[k] = data[k][order]

    t0 = float(data["t_rel_sec"][0])
    t1 = float(data["t_rel_sec"][-1])
    if t1 <= t0:
        raise RuntimeError(f"invalid time range in control CSV: {csv_path}")

    data["u"] = (data["t_rel_sec"] - t0) / (t1 - t0)
    return data

def load_s1_controls(csv_path: Path) -> dict:
    return _load_control_csv(
        csv_path,
        ["t_rel_sec", "intro_breath", "accent_strength", "shadow_shape", "intro_event"],
    )

def load_s2_controls(csv_path: Path) -> dict:
    return _load_control_csv(
        csv_path,
        ["t_rel_sec", "propulsion_envelope", "accent_strength", "lift_shadow", "transition_event"],
    )

def load_s3_controls(csv_path: Path) -> dict:
    return _load_control_csv(
        csv_path,
        ["t_rel_sec", "melody_arc", "accent_strength", "phrase_drive", "melody_event"],
    )

def load_s5_controls(csv_path: Path) -> dict:
    return _load_control_csv(
        csv_path,
        ["t_rel_sec", "drum_envelope", "drum_accent", "drum_velocity", "drum_density", "drum_event"],
    )

def get_control_value(ctrl: dict, name: str, u: float) -> float:
    return _interp_control(ctrl["u"], ctrl[name], u)


# =========================================================
# ボイシング
# =========================================================
def best_voicing(prev, triad, octave_shifts=(-12, 0, 12)):
    inversions = [(0, 1, 2), (1, 2, 0), (2, 0, 1)]
    candidates = []
    for inv in inversions:
        base = [triad[i] for i in inv]
        for s in octave_shifts:
            cand = sorted([p + s for p in base])
            candidates.append(cand)

    if prev is None:
        return min(candidates, key=lambda c: abs(sum(c) / 3 - 67))
    return min(candidates, key=lambda c: sum(abs(c[i] - prev[i]) for i in range(3)))


# =========================================================
# コード辞書
# =========================================================
CH = {
    "G":    [67, 71, 74],
    "D":    [62, 66, 69],
    "Em":   [64, 67, 71],
    "C":    [60, 64, 67],
    "Am":   [69, 72, 76],
    "Bm":   [71, 74, 78],
    "A":    [69, 73, 76],
    "E":    [64, 68, 71],
    "F#m":  [66, 69, 73],
    "D_A":  [62, 66, 69],
}

BASS = {
    "G": 43, "D": 38, "Em": 40, "C": 36, "Am": 45, "Bm": 47,
    "A": 45, "E": 40, "F#m": 42, "D_A": 38,
}


# =========================================================
# セッション設定
# =========================================================
SECTIONS = [
    {"id": "S1", "name": "intro",      "bars": 40, "bpm": 60.8, "note_density": 0.197, "phrase_span": 0.315, "harmonic_tension": 0.174, "inner_voice_swing": 0.684},
    {"id": "S2", "name": "propulsion", "bars": 48, "bpm": 96.0, "note_density": 0.730, "phrase_span": 0.900, "harmonic_tension": 0.896, "inner_voice_swing": 0.194},
    {"id": "S3", "name": "peak1",      "bars": 32, "bpm": 80.0, "note_density": 0.691, "phrase_span": 0.800, "harmonic_tension": 0.560, "inner_voice_swing": 0.110},
    {"id": "S4", "name": "bridge",     "bars": 16, "bpm": 78.4, "note_density": 0.763, "phrase_span": 0.584, "harmonic_tension": 0.371, "inner_voice_swing": 0.070},
    {"id": "S5", "name": "peak2",      "bars": 48, "bpm": 76.8, "note_density": 0.800, "phrase_span": 0.566, "harmonic_tension": 0.315, "inner_voice_swing": 0.171},
    {"id": "S6", "name": "landing",    "bars": 8,  "bpm": 63.3, "note_density": 0.307, "phrase_span": 0.604, "harmonic_tension": 0.344, "inner_voice_swing": 0.833},
]

SECTION_PATTERNS = {
    "S1": ["G", "D", "Em", "C"],
    "S2": ["G", "Am", "C", "D", "Em", "C", "G", "D"],
    "S3": ["G", "D", "Em", "C", "G", "Am", "C", "D"],
    "S4": ["Em", "C", "G", "D"],
    "S5": ["A", "E", "F#m", "D_A", "A", "E", "Bm", "E"],
    "S6": ["A", "D_A", "E", "A"],
}

def build_progression():
    progression = []
    for sec in SECTIONS:
        sid = sec["id"]
        pat = SECTION_PATTERNS[sid]
        bars = sec["bars"]
        for i in range(bars):
            chord = pat[i % len(pat)]
            progression.append(
                {
                    "section_id": sid,
                    "section_name": sec["name"],
                    "section_bar_index": i,
                    "section_bars": bars,
                    "bpm": sec["bpm"],
                    "note_density": sec["note_density"],
                    "phrase_span": sec["phrase_span"],
                    "harmonic_tension": sec["harmonic_tension"],
                    "inner_voice_swing": sec["inner_voice_swing"],
                    "chord": chord,
                }
            )
    return progression

PROGRESSION = build_progression()


# =========================================================
# スケール
# =========================================================
G_MAJOR_PC = {7, 9, 11, 0, 2, 4, 6}
A_MAJOR_PC = {9, 11, 1, 2, 4, 6, 8}
A_SIDE = {"A", "E", "F#m", "Bm", "D_A"}

def scale_pc_for_chord(ch_name: str) -> set:
    return A_MAJOR_PC if ch_name in A_SIDE else G_MAJOR_PC

def nearest_in_scale(midi_note: int, pcs: set) -> int:
    for d in [0, 1, -1, 2, -2, 3, -3]:
        cand = midi_note + d
        if (cand % 12) in pcs:
            return cand
    return midi_note

def step_note_in_scale(note: int, pcs: set, n_steps: int) -> int:
    if n_steps == 0:
        return note
    cur = note
    step_sign = 1 if n_steps > 0 else -1
    for _ in range(abs(n_steps)):
        nxt = cur
        for _k in range(12):
            nxt += step_sign
            if (nxt % 12) in pcs:
                cur = nxt
                break
    return cur


# =========================================================
# 和声テンション
# =========================================================
def tension_extensions(chord_name: str, tension: float) -> list[int]:
    root = BASS[chord_name]
    pcs = scale_pc_for_chord(chord_name)

    exts = []
    if tension >= 0.30:
        exts.append(nearest_in_scale(root + 14, pcs))
    if tension >= 0.60:
        exts.append(nearest_in_scale(root + 10, pcs))
    if tension >= 0.80:
        exts.append(nearest_in_scale(root + 17, pcs))

    out = []
    for n in exts:
        while n < 60:
            n += 12
        while n > 86:
            n -= 12
        out.append(n)

    uniq = []
    for n in out:
        if n not in uniq:
            uniq.append(n)
    return uniq


# =========================================================
# 旋律・伴奏基本ルール
# =========================================================
def melody_range_from_span(span: float) -> tuple[int, int]:
    if span < 0.36:
        return (74, 79)
    if span < 0.66:
        return (73, 84)
    return (72, 88)

def melody_rhythm(note_density: float, bar_dur: float, is_landing: bool) -> list[tuple[float, float]]:
    if is_landing:
        return [(0.00 * bar_dur, 0.70 * bar_dur), (0.76 * bar_dur, 0.18 * bar_dur)]

    if note_density < 0.30:
        return [(0.00, 0.92 * bar_dur)]
    if note_density < 0.60:
        h = bar_dur / 2.0
        return [(0.0, 0.90 * h), (h, 0.90 * h)]
    if note_density < 0.78:
        q = bar_dur / 4.0
        return [(k * q, 0.90 * q) for k in range(4)]
    e = bar_dur / 8.0
    return [(k * e, 0.88 * e) for k in range(8)]

def bass_pattern(note_density: float, root: int, third: int, fifth: int) -> list[int]:
    if note_density < 0.30:
        return [root, fifth]
    if note_density < 0.60:
        return [root, fifth, third, fifth]
    return [root, fifth, third, fifth, root, fifth, third, fifth]

def choose_next_melody_note(prev: int, chord_tones: list[int], pcs: set,
                            target_lo: int, target_hi: int, tseed: float) -> int:
    r = pseudo01(tseed)

    if r < 0.72:
        best = None
        bestdist = 10**9
        for ct in chord_tones:
            for o in (-12, 0, 12):
                cand = ct + o
                while cand < target_lo:
                    cand += 12
                while cand > target_hi:
                    cand -= 12
                dist = abs(cand - prev)
                if dist < bestdist:
                    bestdist = dist
                    best = cand
        note = best if best is not None else prev
    else:
        step = -2 if r < 0.86 else 2
        note = nearest_in_scale(prev + step, pcs)

    while note < target_lo:
        note += 12
    while note > target_hi:
        note -= 12
    return note


# =========================================================
# ダイナミクス
# =========================================================
def dyn_from_features(note_density: float, harmonic_tension: float,
                      inner_voice_swing: float, section_name: str) -> dict:
    base = 46
    piano_chord = base + 18 * harmonic_tension + 8 * note_density
    piano_bass  = base + 10 + 10 * note_density + 8 * harmonic_tension

    if section_name == "intro":
        vn1 = 28 + 12 * harmonic_tension + 6 * note_density
        vn2 = 18 + 8 * harmonic_tension
        va  = 14 + 8 * harmonic_tension
        vc  = 18 + 8 * harmonic_tension + 5 * note_density
    else:
        vn1 = 34 + 36 * harmonic_tension + 10 * note_density
        vn2 = 24 + 20 * harmonic_tension
        va  = 22 + 18 * harmonic_tension + 8 * inner_voice_swing
        vc  = 26 + 18 * harmonic_tension + 10 * note_density

    return {
        "piano_chord": piano_chord,
        "piano_bass": piano_bass,
        "vn1": vn1,
        "vn2": vn2,
        "va": va,
        "vc": vc,
    }


# =========================================================
# 内声の揺れ
# =========================================================
def swing_offset(inner_voice_swing: float, idx: int, subdivision: int, unit: float) -> float:
    if inner_voice_swing < 0.20:
        return 0.0
    mag = min(0.18, 0.03 + 0.12 * inner_voice_swing)
    sign = -1.0 if (idx % 2 == 0) else 1.0
    return sign * mag * unit


# =========================================================
# セクション開始時刻辞書
# =========================================================
def build_section_time_map():
    t = 0.0
    out = {}
    for sec in SECTIONS:
        bpm = sec["bpm"]
        bar_dur = (60.0 / bpm) * BEATS_PER_BAR
        dur = sec["bars"] * bar_dur
        out[sec["id"]] = {
            "start": t,
            "end": t + dur,
            "dur": dur,
            "bars": sec["bars"],
            "bpm": bpm,
            "bar_dur": bar_dur,
        }
        t += dur
    return out

SECTION_TIME_MAP = build_section_time_map()

def section_u(section_id: str, abs_time: float) -> float:
    info = SECTION_TIME_MAP[section_id]
    if info["dur"] <= 0:
        return 0.0
    return clamp((abs_time - info["start"]) / info["dur"], 0.0, 1.0)


# =========================================================
# S1-S2 接続ユーティリティ
# =========================================================
def s1_to_s2_transition_amount_from_s1(bar_start: float) -> float:
    u = section_u("S1", bar_start)
    if u <= 0.90:
        return 0.0
    return clamp((u - 0.90) / 0.10, 0.0, 1.0)

def s2_intro_softness(bar_start: float) -> float:
    u = section_u("S2", bar_start)
    if u >= 0.10:
        return 0.0
    return 1.0 - clamp(u / 0.10, 0.0, 1.0)

def s2_intro_blend_amount(bar_start: float) -> float:
    u = section_u("S2", bar_start)
    if u >= 0.10:
        return 1.0
    return clamp(u / 0.10, 0.0, 1.0)

def s2_first_bar_hardness_cut(bar_start: float) -> float:
    u = section_u("S2", bar_start)
    one_bar_u = 1.0 / max(SECTION_TIME_MAP["S2"]["bars"], 1)
    if u >= one_bar_u:
        return 0.0
    return 1.0 - clamp(u / one_bar_u, 0.0, 1.0)

def s2_intro_bar_phase(bar_start: float) -> int:
    u = section_u("S2", bar_start)
    bars = max(SECTION_TIME_MAP["S2"]["bars"], 1)
    return int(u * bars)

def s2_four_bar_intro_softness(bar_start: float) -> float:
    phase_u = 4.0 / max(SECTION_TIME_MAP["S2"]["bars"], 1)
    u = section_u("S2", bar_start)
    if u >= phase_u:
        return 0.0
    return 1.0 - clamp(u / phase_u, 0.0, 1.0)


# =========================================================
# S1色付けユーティリティ
# =========================================================
def s1_pitch_steps_from_shadow(shadow: float) -> int:
    return int(round(clamp(shadow, -1.0, 1.0) * S1_PITCH_STEPS_MAX))

def s1_duration_scale(breath: float, u: float = 0.0) -> float:
    scale = 1.0 - S1_DUR_GAIN * clamp(breath, -1.0, 1.0)
    tail_push = 0.0
    if u > 0.72:
        tail_push = 0.08 * ((u - 0.72) / 0.28)
    scale = scale * (1.0 - tail_push)
    return clamp(scale, 0.88, 1.10)

def s1_velocity_delta_from_accent(accent_strength_01: float, gain: float) -> float:
    centered = to_centered_from_01(accent_strength_01)
    return gain * centered

def s1_tail_boost(u: float, max_gain: float) -> float:
    if u <= 0.72:
        return 0.0
    x = (u - 0.72) / 0.28
    x = clamp(x, 0.0, 1.0)
    return max_gain * x

def s1_chord_register_shift(shadow: float) -> int:
    shadow = clamp(shadow, -1.0, 1.0)
    if shadow > 0.35:
        return 12
    if shadow < -0.35:
        return -12
    return 0


# =========================================================
# S2色付けユーティリティ
# =========================================================
def s2_pitch_steps_from_lift(lift: float) -> int:
    return int(round(clamp(lift, -1.0, 1.0) * S2_PITCH_STEPS_MAX))

def s2_duration_scale(propulsion: float) -> float:
    scale = 1.0 - S2_DUR_GAIN * clamp(propulsion, -1.0, 1.0)
    return clamp(scale, 0.86, 1.12)

def s2_velocity_delta_from_accent(accent_strength_01: float, gain: float) -> float:
    centered = to_centered_from_01(accent_strength_01)
    return gain * centered


# =========================================================
# S3色付けユーティリティ
# =========================================================
def s3_pitch_steps_from_arc(arc: float) -> int:
    return int(round(clamp(arc, -1.0, 1.0) * S3_PITCH_STEPS_MAX))

def s3_duration_scale(phrase_drive: float) -> float:
    scale = 1.0 - S3_DUR_GAIN * clamp(phrase_drive, -1.0, 1.0)
    return clamp(scale, 0.80, 1.20)

def s3_velocity_delta_from_accent(accent_strength_01: float, gain: float) -> float:
    centered = to_centered_from_01(accent_strength_01)
    return gain * centered


# =========================================================
# 弦パート追加
# =========================================================
def add_string_parts(vn1, vn2, va, vc, chord_name, triad_voiced,
                     bar_start, bar_dur, feature_row, dyn, bar_global_index,
                     s1_ctrl: dict | None, s1_state: dict,
                     s2_ctrl: dict | None, s2_state: dict,
                     s3_ctrl: dict | None, s3_state: dict):
    section_id = feature_row["section_id"]
    section_name = feature_row["section_name"]
    note_density = feature_row["note_density"]
    phrase_span = feature_row["phrase_span"]
    harmonic_tension = feature_row["harmonic_tension"]
    inner_voice_swing = feature_row["inner_voice_swing"]

    if section_name == "intro" and dyn["vn1"] <= 0:
        return

    pcs = scale_pc_for_chord(chord_name)
    chord_tones = triad_voiced[:]
    target_lo, target_hi = melody_range_from_span(phrase_span)

    chord_tones_mel = []
    for ct in chord_tones:
        x = ct
        while x < 76:
            x += 12
        chord_tones_mel.append(x)

    rhy = melody_rhythm(note_density, bar_dur, section_name == "landing")
    rhy_use = rhy

    if section_id == "S1" and s1_ctrl is not None:
        u_sec = section_u("S1", bar_start)
        _ = get_control_value(s1_ctrl, "intro_breath", u_sec)
        e = bar_dur / 8.0

        if u_sec < 0.22:
            rhy_use = [
                (0.0 * e, 0.62 * e),
                (2.0 * e, 0.62 * e),
                (4.0 * e, 0.62 * e),
                (6.0 * e, 1.10 * e),
            ]
        elif u_sec < 0.78:
            rhy_use = [
                (0.0 * e, 0.58 * e),
                (1.5 * e, 0.52 * e),
                (3.0 * e, 0.58 * e),
                (4.5 * e, 0.52 * e),
                (6.0 * e, 0.90 * e),
            ]
        else:
            rhy_use = [
                (0.0 * e, 0.56 * e),
                (1.5 * e, 0.50 * e),
                (3.0 * e, 0.56 * e),
                (4.5 * e, 0.50 * e),
                (6.0 * e, 1.35 * e),
            ]

    elif section_id == "S2":
        phase = s2_intro_bar_phase(bar_start)
        q = bar_dur / 4.0

        if phase == 0:
            rhy_use = [
                (0.00 * q, 0.42 * q),
                (2.00 * q, 0.52 * q),
                (3.00 * q, 0.60 * q),
            ]
        elif phase == 1:
            rhy_use = [
                (0.00 * q, 0.46 * q),
                (1.50 * q, 0.40 * q),
                (2.50 * q, 0.44 * q),
                (3.25 * q, 0.54 * q),
            ]
        elif phase == 2:
            rhy_use = [
                (0.00 * q, 0.52 * q),
                (1.00 * q, 0.42 * q),
                (2.00 * q, 0.44 * q),
                (3.00 * q, 0.58 * q),
            ]
        elif phase == 3:
            rhy_use = [
                (0.00 * q, 0.56 * q),
                (1.00 * q, 0.46 * q),
                (2.00 * q, 0.46 * q),
                (3.00 * q, 0.62 * q),
            ]

    if rhy_use:
        seed = bar_global_index * 0.71 + len(chord_name) * 0.13
        prev = chord_tones_mel[int(pseudo01(seed) * len(chord_tones_mel)) % len(chord_tones_mel)]

        for j, (off, dur) in enumerate(rhy_use):
            base_start = bar_start + off
            base_note = choose_next_melody_note(
                prev, chord_tones_mel, pcs, target_lo, target_hi, seed + j * 0.31
            )
            note = base_note
            vel = dyn["vn1"]
            note_dur = dur

            if section_id == "S1" and s1_ctrl is not None:
                u = section_u("S1", base_start)
                breath = get_control_value(s1_ctrl, "intro_breath", u)
                accent01 = get_control_value(s1_ctrl, "accent_strength", u)
                shadow = get_control_value(s1_ctrl, "shadow_shape", u)
                event = get_control_value(s1_ctrl, "intro_event", u)

                steps = s1_pitch_steps_from_shadow(shadow)
                note = step_note_in_scale(base_note, pcs, steps)

                while note < target_lo:
                    note += 12
                while note > target_hi:
                    note -= 12

                vel += s1_velocity_delta_from_accent(accent01, S1_VEL_GAIN_VN1)
                vel += s1_tail_boost(u, 16.0)
                note_dur = dur * s1_duration_scale(breath, u)

                bar_local = (base_start - bar_start) / max(bar_dur, 1e-9)
                if bar_local < 0.16:
                    vel -= 10
                elif bar_local < 0.32:
                    vel -= 5
                elif bar_local > 0.72:
                    vel += 2

                if event > S1_EVENT_THRESHOLD:
                    last_event_t = s1_state.get("last_vn1_event_t", -1e9)
                    if (base_start - last_event_t) >= S1_MIN_EVENT_GAP_SEC:
                        grace_pitch = step_note_in_scale(note, pcs, 1 if shadow >= 0 else -1)
                        grace_dur = max(0.05, min(note_dur * S1_GRACE_RATIO, 0.16))
                        grace_start = max(bar_start, base_start - grace_dur * 0.82)
                        grace_end = grace_start + grace_dur
                        add_note(vn1, grace_pitch, grace_start, grace_end, vel - S1_EVENT_VEL_DROP)
                        s1_state["last_vn1_event_t"] = base_start

            elif section_id == "S2" and s2_ctrl is not None:
                u = section_u("S2", base_start)
                propulsion = get_control_value(s2_ctrl, "propulsion_envelope", u)
                accent01 = get_control_value(s2_ctrl, "accent_strength", u)
                lift = get_control_value(s2_ctrl, "lift_shadow", u)
                event = get_control_value(s2_ctrl, "transition_event", u)
                soft = s2_intro_softness(base_start)
                hard_cut = s2_first_bar_hardness_cut(base_start)
                soft4 = s2_four_bar_intro_softness(base_start)

                steps = s2_pitch_steps_from_lift(lift)
                note = step_note_in_scale(base_note, pcs, steps)

                while note < target_lo:
                    note += 12
                while note > target_hi:
                    note -= 12

                vel += s2_velocity_delta_from_accent(accent01, S2_VEL_GAIN_VN1)
                if u < 0.12:
                    vel -= 6 * (1.0 - u / 0.12)

                vel -= 4 * soft4 + 8 * soft + 10 * hard_cut

                bar_local = (base_start - bar_start) / max(bar_dur, 1e-9)
                if hard_cut > 0.0:
                    if bar_local < 0.10:
                        vel -= 8
                    elif bar_local < 0.60:
                        vel -= 2
                    else:
                        vel += 2

                note_dur = dur * s2_duration_scale(propulsion) * (1.0 + 0.05 * soft4 + 0.06 * soft + 0.10 * hard_cut)

                if event > S2_EVENT_THRESHOLD and hard_cut < 0.25:
                    last_event_t = s2_state.get("last_vn1_event_t", -1e9)
                    if (base_start - last_event_t) >= S2_MIN_EVENT_GAP_SEC:
                        grace_pitch = step_note_in_scale(note, pcs, 1 if lift >= 0 else -1)
                        grace_dur = max(0.05, min(note_dur * S2_GRACE_RATIO, 0.14))
                        grace_start = max(bar_start, base_start - grace_dur * 0.85)
                        grace_end = grace_start + grace_dur
                        add_note(vn1, grace_pitch, grace_start, grace_end, vel - S2_EVENT_VEL_DROP)
                        s2_state["last_vn1_event_t"] = base_start

            elif section_id == "S3" and s3_ctrl is not None:
                u = section_u("S3", base_start)
                arc = get_control_value(s3_ctrl, "melody_arc", u)
                accent01 = get_control_value(s3_ctrl, "accent_strength", u)
                drive = get_control_value(s3_ctrl, "phrase_drive", u)
                event = get_control_value(s3_ctrl, "melody_event", u)

                steps = s3_pitch_steps_from_arc(arc)
                note = step_note_in_scale(base_note, pcs, steps)

                while note < target_lo:
                    note += 12
                while note > target_hi:
                    note -= 12

                vel += s3_velocity_delta_from_accent(accent01, S3_VEL_GAIN_VN1)
                note_dur = dur * s3_duration_scale(drive)

                if event > S3_EVENT_THRESHOLD:
                    last_event_t = s3_state.get("last_vn1_event_t", -1e9)
                    if (base_start - last_event_t) >= S3_MIN_EVENT_GAP_SEC:
                        grace_pitch = step_note_in_scale(note, pcs, -1 if arc >= 0 else 1)
                        grace_dur = max(0.06, min(note_dur * S3_GRACE_RATIO, 0.18))
                        grace_start = max(bar_start, base_start - grace_dur * 0.90)
                        grace_end = grace_start + grace_dur
                        add_note(vn1, grace_pitch, grace_start, grace_end, vel - S3_EVENT_VEL_DROP)
                        s3_state["last_vn1_event_t"] = base_start

            if section_id == "S1" and s1_ctrl is not None:
                u = section_u("S1", base_start)
                shadow = get_control_value(s1_ctrl, "shadow_shape", u)
                trans = s1_to_s2_transition_amount_from_s1(base_start)

                if note_dur < 0.28 or u < 0.30 or trans > 0.45:
                    prev = note
                    add_note(vn1, note, base_start, base_start + note_dur, vel + 2 * trans)
                else:
                    tail_ratio = 0.18 - 0.08 * trans
                    split_t = base_start + note_dur * (1.0 - tail_ratio)

                    tail_step = 1 if shadow >= 0 else -1
                    tail_note = step_note_in_scale(note, pcs, tail_step)

                    while tail_note < target_lo:
                        tail_note += 12
                    while tail_note > target_hi:
                        tail_note -= 12

                    add_note(vn1, note, base_start, split_t, vel)
                    add_note(vn1, tail_note, split_t, base_start + note_dur, vel - 3)
                    prev = tail_note
            else:
                prev = note
                add_note(vn1, note, base_start, base_start + note_dur, vel)

    if dyn["vn2"] > 0:
        upper = sorted([p + 7 for p in triad_voiced])
        note = upper[0]
        while note < 67:
            note += 12
        hold = 0.98 if harmonic_tension < 0.7 else 0.92
        vel_vn2 = dyn["vn2"]

        if section_id == "S1":
            u_bar = section_u("S1", bar_start)
            vel_vn2 += s1_tail_boost(u_bar, 6.0)

        if section_id == "S2":
            soft = s2_intro_softness(bar_start)
            hard_cut = s2_first_bar_hardness_cut(bar_start)
            soft4 = s2_four_bar_intro_softness(bar_start)
            vel_vn2 -= 2 * soft4 + 4 * soft + 6 * hard_cut

        add_note(vn2, note, bar_start, bar_start + bar_dur * hold, vel_vn2)

    if dyn["va"] > 0:
        mid = sorted(triad_voiced)[1]
        while mid < 58:
            mid += 12

        if inner_voice_swing < 0.20:
            vel_va = dyn["va"]
            if section_id == "S1":
                u_bar = section_u("S1", bar_start)
                vel_va += s1_tail_boost(u_bar, 5.0)
            if section_id == "S2":
                soft = s2_intro_softness(bar_start)
                hard_cut = s2_first_bar_hardness_cut(bar_start)
                soft4 = s2_four_bar_intro_softness(bar_start)
                vel_va -= 2 * soft4 + 4 * soft + 5 * hard_cut
            add_note(va, mid, bar_start, bar_start + bar_dur * 0.95, vel_va)
        else:
            h = bar_dur / 2.0
            for k in range(2):
                st = bar_start + k * h + swing_offset(inner_voice_swing, k, 2, h)
                en = st + h * 0.82
                vel_va = dyn["va"] - 2
                if section_id == "S1":
                    u_seg = section_u("S1", st)
                    vel_va += s1_tail_boost(u_seg, 5.0)
                if section_id == "S2":
                    soft = s2_intro_softness(st)
                    hard_cut = s2_first_bar_hardness_cut(st)
                    soft4 = s2_four_bar_intro_softness(st)
                    vel_va -= 2 * soft4 + 4 * soft + 5 * hard_cut
                add_note(va, mid, st, en, vel_va)

    if dyn["vc"] > 0:
        root = BASS.get(chord_name, min(triad_voiced) - 24)
        if note_density < 0.60:
            vel_vc = dyn["vc"]
            if section_id == "S1":
                u_bar = section_u("S1", bar_start)
                vel_vc += s1_tail_boost(u_bar, 6.0)
            if section_id == "S2":
                soft = s2_intro_softness(bar_start)
                hard_cut = s2_first_bar_hardness_cut(bar_start)
                soft4 = s2_four_bar_intro_softness(bar_start)
                vel_vc -= 2 * soft4 + 4 * soft + 6 * hard_cut
            add_note(vc, root, bar_start, bar_start + bar_dur * 0.98, vel_vc)
        else:
            h = bar_dur / 2.0
            fifth = root + 7

            vel_vc1 = dyn["vc"]
            vel_vc2 = dyn["vc"] - 2

            if section_id == "S1":
                u1 = section_u("S1", bar_start)
                u2 = section_u("S1", bar_start + h)
                vel_vc1 += s1_tail_boost(u1, 6.0)
                vel_vc2 += s1_tail_boost(u2, 6.0)

            if section_id == "S2":
                soft1 = s2_intro_softness(bar_start)
                hard1 = s2_first_bar_hardness_cut(bar_start)
                soft41 = s2_four_bar_intro_softness(bar_start)
                soft2 = s2_intro_softness(bar_start + h)
                hard2 = s2_first_bar_hardness_cut(bar_start + h)
                soft42 = s2_four_bar_intro_softness(bar_start + h)
                vel_vc1 -= 2 * soft41 + 4 * soft1 + 6 * hard1
                vel_vc2 -= 2 * soft42 + 4 * soft2 + 4 * hard2

            add_note(vc, root, bar_start, bar_start + h * 0.92, vel_vc1)
            add_note(vc, fifth, bar_start + h, bar_start + h + h * 0.92, vel_vc2)


# =========================================================
# S1 ドラム追加（細かめ・控えめ）
# =========================================================
def add_s1_drum_parts(drum_inst, bar_start: float, bar_dur: float, s1_ctrl: dict):
    eighth = bar_dur / 8.0
    sixteenth = bar_dur / 16.0

    u_bar = section_u("S1", bar_start)
    breath = get_control_value(s1_ctrl, "intro_breath", u_bar)
    accent01 = get_control_value(s1_ctrl, "accent_strength", u_bar)
    shadow = get_control_value(s1_ctrl, "shadow_shape", u_bar)
    event = get_control_value(s1_ctrl, "intro_event", u_bar)

    env = abs(clamp(breath, -1.0, 1.0))
    acc = to_centered_from_01(accent01)

    kick_vel = clamp(46 + 10 * env + 6 * acc, 22, 64)
    tom_vel  = clamp(kick_vel - 8, 16, 56)
    sub_vel  = clamp(kick_vel - 14, 12, 46)

    for k in range(8):
        st = bar_start + k * eighth

        if k % 2 == 0:
            vel = kick_vel
            if k == 0:
                vel += 1
            elif k == 4:
                vel += 1
            elif k in (2, 6):
                vel -= 1
            if u_bar > 0.70 and k == 6:
                vel += 3

            add_note(drum_inst, DRUM_SOFT_KICK, st, st + eighth * 0.24, clamp(vel, 22, 82))
        else:
            vel = tom_vel
            if shadow >= 0:
                vel += 2
            if u_bar > 0.55 and k in (5, 7):
                vel += 2

            add_note(drum_inst, DRUM_SOFT_TOM, st, st + eighth * 0.20, clamp(vel, 18, 70))

    if event > 0.50:
        extra_positions = [1.5, 5.5] if u_bar < 0.72 else [3.5, 6.5]
        for pos in extra_positions:
            st = bar_start + pos * eighth
            add_note(drum_inst, DRUM_SOFT_TOM, st, st + sixteenth * 0.42, clamp(sub_vel + 4, 14, 48))

    if u_bar > 0.78:
        st = bar_start + 7.5 * eighth
        add_note(drum_inst, DRUM_SOFT_KICK, st, st + sixteenth * 0.36, clamp(sub_vel + 6, 16, 50))

    if u_bar >= 0.90:
        for k in [0, 2, 4, 6]:
            st = bar_start + k * eighth
            add_note(
                drum_inst,
                DRUM_SOFT_HH,
                st,
                st + sixteenth * 0.20,
                clamp(18 + 8 * ((u_bar - 0.90) / 0.10), 16, 28),
            )


# =========================================================
# S3 ドラム追加（控えめ）
# =========================================================
def add_s3_drum_parts(drum_inst, bar_start: float, bar_dur: float, s3_ctrl: dict):
    quarter = bar_dur / 4.0
    eighth = bar_dur / 8.0

    for beat in range(4):
        st = bar_start + beat * quarter
        u = section_u("S3", st)

        arc = get_control_value(s3_ctrl, "melody_arc", u)
        accent01 = get_control_value(s3_ctrl, "accent_strength", u)
        drive = get_control_value(s3_ctrl, "phrase_drive", u)
        event = get_control_value(s3_ctrl, "melody_event", u)

        arc_abs = abs(clamp(arc, -1.0, 1.0))

        kick_vel = clamp(64 + 18 * arc_abs + 12 * to_centered_from_01(accent01), 44, 104)
        tom_vel  = clamp(kick_vel - 12 + 10 * max(drive, 0.0), 34, 88)

        add_note(drum_inst, DRUM_SOFT_KICK, st, st + eighth * 0.45, kick_vel)
        add_note(drum_inst, DRUM_SOFT_TOM, st + eighth, st + eighth + eighth * 0.38, tom_vel)

        if event > 0.35:
            add_note(
                drum_inst,
                DRUM_SOFT_KICK,
                st + quarter * 0.72,
                st + quarter * 0.72 + eighth * 0.26,
                clamp(kick_vel - 10, 30, 84),
            )


# =========================================================
# S5 ドラム追加（ボレロ型）
# =========================================================
def s5_base_snare_velocity(env: float, accent: float, vel01: float) -> float:
    env_abs = abs(clamp(env, -1.0, 1.0))
    v = (
        S5_SNARE_BASE_VEL
        + S5_SNARE_ENV_GAIN * env_abs
        + S5_SNARE_ACCENT_GAIN * clamp(accent, 0.0, 1.0)
        + S5_SNARE_VELOCITY_GAIN * to_centered_from_01(clamp(vel01, 0.0, 1.0))
    )
    return clamp(v, 26, 110)

def add_s5_drum_parts(drum_inst, bar_start: float, bar_dur: float, s5_ctrl: dict):
    sixteenth = bar_dur / 16.0

    for beat in range(4):
        beat_start = bar_start + beat * 4 * sixteenth

        u = section_u("S5", beat_start)
        env = get_control_value(s5_ctrl, "drum_envelope", u)
        accent = get_control_value(s5_ctrl, "drum_accent", u)
        vel01 = get_control_value(s5_ctrl, "drum_velocity", u)
        density = get_control_value(s5_ctrl, "drum_density", u)
        event = get_control_value(s5_ctrl, "drum_event", u)

        env_abs = abs(clamp(env, -1.0, 1.0))
        base_vel = s5_base_snare_velocity(env, accent, vel01)

        if density >= S5_DENSITY_KEEP4_TH:
            hit_steps = [0, 1, 2, 3]
        elif density >= S5_DENSITY_KEEP3_TH:
            hit_steps = [0, 1, 3]
        else:
            hit_steps = [0, 2]

        head_boost = S5_YAW_STRONG_GAIN * env_abs if env_abs >= S5_YAW_PEAK_THRESHOLD else 0.0

        for step in hit_steps:
            st = beat_start + step * sixteenth

            if step == 0:
                vel = clamp(base_vel + 12 + head_boost, 24, 122)
                dur = sixteenth * 1.55
            else:
                vel = clamp(base_vel - 6 + 4.0 * accent + 3.0 * env_abs, 18, 96)
                dur = sixteenth * 0.92

            if env_abs >= S5_YAW_PEAK_THRESHOLD and step == hit_steps[-1] and len(hit_steps) >= 3:
                vel = clamp(vel + 4, 18, 100)

            add_note(drum_inst, DRUM_SNARE_MAIN, st, st + dur, vel)

        bd_vel = clamp(base_vel - S5_BD_UNDERLAY_DROP + 8 * env_abs, 6, 46)
        add_note(drum_inst, DRUM_BD_SUB, beat_start, beat_start + sixteenth * 0.85, bd_vel)

        hh_vel = clamp(base_vel - S5_HH_DROP + 6 * accent, 4, 28)
        add_note(drum_inst, DRUM_CLOSED_HH, beat_start, beat_start + sixteenth * 0.18, hh_vel)

        if event >= S5_EVENT_THRESHOLD:
            extra_st = beat_start + 2.5 * sixteenth
            extra_vel = clamp(base_vel - S5_EXTRA_HIT_DROP + 10 * accent + 8 * env_abs, 18, 98)

            if env_abs >= S5_YAW_PEAK_THRESHOLD:
                add_note(drum_inst, DRUM_BD_SUB, extra_st, extra_st + sixteenth * 0.70, extra_vel)
            else:
                add_note(
                    drum_inst,
                    DRUM_CLOSED_HH,
                    extra_st,
                    extra_st + sixteenth * 0.35,
                    clamp(extra_vel - 10, 8, 54),
                )


# =========================================================
# 制御データ
# =========================================================
S1_CTRL = load_s1_controls(S1_CONTROL_CSV)
S1_STATE = {"last_vn1_event_t": -1e9}

S2_CTRL = load_s2_controls(S2_CONTROL_CSV)
S2_STATE = {"last_vn1_event_t": -1e9}

S3_CTRL = load_s3_controls(S3_CONTROL_CSV)
S3_STATE = {"last_vn1_event_t": -1e9}

S5_CTRL = load_s5_controls(S5_CONTROL_CSV)


# =========================================================
# MIDI 作成
# =========================================================
pm = pretty_midi.PrettyMIDI(initial_tempo=SECTIONS[0]["bpm"])

piano = pretty_midi.Instrument(program=pretty_midi.instrument_name_to_program("Acoustic Grand Piano"))
vn1   = pretty_midi.Instrument(program=pretty_midi.instrument_name_to_program("Violin"))
vn2   = pretty_midi.Instrument(program=pretty_midi.instrument_name_to_program("Violin"))
va    = pretty_midi.Instrument(program=pretty_midi.instrument_name_to_program("Viola"))
vc    = pretty_midi.Instrument(program=pretty_midi.instrument_name_to_program("Cello"))
drums = pretty_midi.Instrument(program=0, is_drum=True, name="Section Drum Layer")

t = 0.0
prev_voicing = None

for i, row in enumerate(PROGRESSION):
    section_id = row["section_id"]
    chord_name = row["chord"]
    section_name = row["section_name"]
    bpm = row["bpm"]
    note_density = row["note_density"]
    harmonic_tension = row["harmonic_tension"]
    inner_voice_swing = row["inner_voice_swing"]

    sec_per_beat = 60.0 / bpm
    bar_dur = sec_per_beat * BEATS_PER_BAR

    triad_raw = CH[chord_name]
    triad = best_voicing(prev_voicing, triad_raw)
    prev_voicing = triad

    dyn = dyn_from_features(
        note_density=note_density,
        harmonic_tension=harmonic_tension,
        inner_voice_swing=inner_voice_swing,
        section_name=section_name,
    )

    root = BASS.get(chord_name, min(triad_raw) - 24)
    is_minor = chord_name.endswith("m")
    third = root + (3 if is_minor else 4)
    fifth = root + 7

    # Piano chord
    ext_notes = tension_extensions(chord_name, harmonic_tension)

    hold_ratio = 0.96
    if note_density >= 0.75:
        hold_ratio = 0.88
    elif note_density >= 0.60:
        hold_ratio = 0.92

    if section_id == "S1":
        u_bar = section_u("S1", t)
        breath = get_control_value(S1_CTRL, "intro_breath", u_bar)
        hold_ratio = clamp(hold_ratio * s1_duration_scale(breath, u_bar), 0.88, 1.08)
        if u_bar > 0.88:
            hold_ratio = clamp(hold_ratio * 1.16, 0.90, 1.16)

    elif section_id == "S2":
        u_bar = section_u("S2", t)
        propulsion = get_control_value(S2_CTRL, "propulsion_envelope", u_bar)
        hold_ratio = clamp(hold_ratio * s2_duration_scale(propulsion), 0.82, 1.00)
        soft = s2_intro_softness(t)
        hold_ratio = clamp(hold_ratio * (1.0 + 0.08 * soft), 0.82, 1.06)

    elif section_id == "S3":
        u_bar = section_u("S3", t)
        drive = get_control_value(S3_CTRL, "phrase_drive", u_bar)
        hold_ratio = clamp(hold_ratio * s3_duration_scale(drive), 0.76, 1.02)

    piano_chord_vel = dyn["piano_chord"]
    piano_ext_vel = dyn["piano_chord"] - 8
    chord_reg_shift = 0

    if section_id == "S1":
        u_bar = section_u("S1", t)
        shadow = get_control_value(S1_CTRL, "shadow_shape", u_bar)
        chord_reg_shift = s1_chord_register_shift(shadow)

        piano_chord_vel -= 10
        piano_ext_vel -= 12
        piano_chord_vel += s1_tail_boost(u_bar, 3.0)
        piano_ext_vel += s1_tail_boost(u_bar, 2.0)

        trans = s1_to_s2_transition_amount_from_s1(t)
        hold_ratio = clamp(hold_ratio * (1.0 - 0.10 * trans), 0.84, 1.08)
        piano_chord_vel += 6 * trans
        piano_ext_vel += 4 * trans

    elif section_id == "S2":
        soft = s2_intro_softness(t)
        hard_cut = s2_first_bar_hardness_cut(t)
        soft4 = s2_four_bar_intro_softness(t)
        piano_chord_vel -= 4 * soft4 + 8 * soft + 10 * hard_cut
        piano_ext_vel  -= 3 * soft4 + 6 * soft + 8 * hard_cut

    chord_end = t + bar_dur * hold_ratio
    ext_end = t + bar_dur * max(0.70, hold_ratio - 0.10)

    if section_id == "S1":
        u_bar = section_u("S1", t)
        if u_bar > 0.965:
            chord_end += 1.6
            ext_end += 1.2

    chord_tones_to_play = triad
    ext_notes_to_play = ext_notes

    if section_id == "S1":
        u_bar = section_u("S1", t)
        chord_tones_to_play = thin_s1_chord_tones(triad, u_bar)
        ext_notes_to_play = ext_notes[:1] if u_bar < 0.60 else ext_notes

    elif section_id == "S2":
        phase = s2_intro_bar_phase(t)

        if phase == 0:
            chord_tones_to_play = sorted(triad)[1:]
            ext_notes_to_play = []
        elif phase == 1:
            chord_tones_to_play = sorted(triad)[1:]
            ext_notes_to_play = ext_notes[:1]
        elif phase == 2:
            chord_tones_to_play = triad
            ext_notes_to_play = ext_notes[:1]
        elif phase == 3:
            chord_tones_to_play = triad
            ext_notes_to_play = ext_notes[:1]
        else:
            chord_tones_to_play = triad
            ext_notes_to_play = ext_notes

    for p in chord_tones_to_play:
        add_note(piano, p + chord_reg_shift, t, chord_end, piano_chord_vel)
    for p in ext_notes_to_play:
        add_note(piano, p + chord_reg_shift, t, ext_end, piano_ext_vel)

    # Piano bass / ostinato
    pat = bass_pattern(note_density, root, third, fifth)

    if section_id == "S2":
        phase = s2_intro_bar_phase(t)

        if phase == 0:
            if len(pat) >= 8:
                pat = [pat[0], pat[4]]
            elif len(pat) >= 4:
                pat = [pat[0], pat[2]]
            elif len(pat) >= 2:
                pat = [pat[0], pat[1]]

        elif phase == 1:
            if len(pat) >= 8:
                pat = [pat[0], pat[2], pat[4]]
            elif len(pat) >= 4:
                pat = [pat[0], pat[2], pat[3]]

        elif phase == 2:
            if len(pat) >= 8:
                pat = [pat[0], pat[2], pat[4], pat[6]]
            elif len(pat) >= 4:
                pat = [pat[0], pat[1], pat[2], pat[3]]

        elif phase == 3:
            if len(pat) >= 8:
                pat = [pat[0], pat[1], pat[3], pat[4], pat[6], pat[7]]

    if len(pat) == 1:
        st = t
        en = st + bar_dur * 0.82
        vel = dyn["piano_bass"] - 6

        if section_id == "S2":
            u = section_u("S2", st)
            accent01 = get_control_value(S2_CTRL, "accent_strength", u)
            propulsion = get_control_value(S2_CTRL, "propulsion_envelope", u)
            soft = s2_intro_softness(st)
            hard_cut = s2_first_bar_hardness_cut(st)
            soft4 = s2_four_bar_intro_softness(st)

            vel += s2_velocity_delta_from_accent(accent01, S2_VEL_GAIN_BASS)
            vel -= 4 * soft4 + 12 * soft + 14 * hard_cut
            en = st + (bar_dur * 0.82) * s2_duration_scale(propulsion) * (1.0 + 0.04 * soft4 + 0.08 * soft + 0.10 * hard_cut)

        add_note(piano, pat[0], st, en, vel)

    elif len(pat) == 2:
        half = bar_dur / 2.0

        if section_id == "S1":
            u_bar = section_u("S1", t)
            s1_pat = thin_s1_bass_pattern(pat, u_bar)
            for idx, note in s1_pat:
                st = t + idx * half
                en = st + half * 0.52

                vel = dyn["piano_bass"] - 16
                u = section_u("S1", st)
                breath = get_control_value(S1_CTRL, "intro_breath", u)

                vel += s1_tail_boost(u, 2.0)
                en = st + (half * 0.52) * s1_duration_scale(breath, u)
                vel, en = apply_s1_piano_head_control(vel, st, t, bar_dur, en)
                add_note(piano, note, st, en, vel)

        else:
            for k, note in enumerate(pat):
                st = t + k * half
                en = st + half * 0.92

                head_boost = 5 if k == 0 else 0
                vel = dyn["piano_bass"] + head_boost

                if section_id == "S2":
                    u = section_u("S2", st)
                    accent01 = get_control_value(S2_CTRL, "accent_strength", u)
                    propulsion = get_control_value(S2_CTRL, "propulsion_envelope", u)
                    soft = s2_intro_softness(st)
                    hard_cut = s2_first_bar_hardness_cut(st)
                    soft4 = s2_four_bar_intro_softness(st)

                    vel += s2_velocity_delta_from_accent(accent01, S2_VEL_GAIN_BASS)
                    if u < 0.12:
                        vel -= 4 * (1.0 - u / 0.12)

                    vel -= 4 * soft4 + 10 * soft + 10 * hard_cut
                    en = st + (half * 0.92) * s2_duration_scale(propulsion) * (1.0 + 0.04 * soft4 + 0.08 * soft + 0.06 * hard_cut)

                elif section_id == "S3":
                    u = section_u("S3", st)
                    accent01 = get_control_value(S3_CTRL, "accent_strength", u)
                    drive = get_control_value(S3_CTRL, "phrase_drive", u)
                    vel += s3_velocity_delta_from_accent(accent01, S3_VEL_GAIN_BASS)
                    en = st + (half * 0.92) * s3_duration_scale(drive)

                add_note(piano, note, st, en, vel)

    elif len(pat) == 4:
        quarter = bar_dur / 4.0

        if section_id == "S1":
            u_bar = section_u("S1", t)
            s1_pat = thin_s1_bass_pattern(pat, u_bar)
            for idx, note in s1_pat:
                st = t + idx * quarter
                en = st + quarter * 0.48

                u = section_u("S1", st)
                breath = get_control_value(S1_CTRL, "intro_breath", u)

                vel = dyn["piano_bass"] - 18
                vel += s1_tail_boost(u, 2.0)

                en = st + (quarter * 0.48) * s1_duration_scale(breath, u)
                vel, en = apply_s1_piano_head_control(vel, st, t, bar_dur, en)
                add_note(piano, note, st, en, vel)

        else:
            for k, note in enumerate(pat):
                st = t + k * quarter
                en = st + quarter * 0.90

                vel = dyn["piano_bass"] + (6 if k in (0, 2) else 0)

                if section_id == "S2":
                    u = section_u("S2", st)
                    accent01 = get_control_value(S2_CTRL, "accent_strength", u)
                    propulsion = get_control_value(S2_CTRL, "propulsion_envelope", u)
                    soft = s2_intro_softness(st)
                    hard_cut = s2_first_bar_hardness_cut(st)
                    soft4 = s2_four_bar_intro_softness(st)

                    vel += s2_velocity_delta_from_accent(accent01, S2_VEL_GAIN_BASS)
                    if u < 0.12:
                        vel -= 4 * (1.0 - u / 0.12)

                    vel -= 3 * soft4 + 9 * soft + 8 * hard_cut
                    en = st + (quarter * 0.90) * s2_duration_scale(propulsion) * (1.0 + 0.03 * soft4 + 0.06 * soft + 0.04 * hard_cut)

                elif section_id == "S3":
                    u = section_u("S3", st)
                    accent01 = get_control_value(S3_CTRL, "accent_strength", u)
                    drive = get_control_value(S3_CTRL, "phrase_drive", u)
                    vel += s3_velocity_delta_from_accent(accent01, S3_VEL_GAIN_BASS)
                    en = st + (quarter * 0.90) * s3_duration_scale(drive)

                add_note(piano, note, st, en, vel)

    else:
        eighth = bar_dur / 8.0

        if section_id == "S1":
            u_bar = section_u("S1", t)
            s1_pat = thin_s1_bass_pattern(pat, u_bar)
            for idx, note in s1_pat:
                off = swing_offset(inner_voice_swing, idx, 8, eighth)
                st = t + idx * eighth + off
                en = st + eighth * 0.42

                u = section_u("S1", st)
                breath = get_control_value(S1_CTRL, "intro_breath", u)

                vel = dyn["piano_bass"] - 20
                vel += s1_tail_boost(u, 1.5)

                en = st + (eighth * 0.42) * s1_duration_scale(breath, u)
                vel, en = apply_s1_piano_head_control(vel, st, t, bar_dur, en)
                add_note(piano, note, st, en, vel)

        else:
            for k, note in enumerate(pat):
                off = swing_offset(inner_voice_swing, k, 8, eighth)
                st = t + k * eighth + off
                en = st + eighth * 0.84

                vel = dyn["piano_bass"] + (7 if k in (0, 4) else 0)

                if section_id == "S2":
                    u = section_u("S2", st)
                    accent01 = get_control_value(S2_CTRL, "accent_strength", u)
                    propulsion = get_control_value(S2_CTRL, "propulsion_envelope", u)
                    soft = s2_intro_softness(st)
                    hard_cut = s2_first_bar_hardness_cut(st)
                    soft4 = s2_four_bar_intro_softness(st)

                    vel += s2_velocity_delta_from_accent(accent01, S2_VEL_GAIN_BASS)
                    if u < 0.12:
                        vel -= 4 * (1.0 - u / 0.12)

                    vel -= 3 * soft4 + 8 * soft + 6 * hard_cut
                    en = st + (eighth * 0.84) * s2_duration_scale(propulsion) * (1.0 + 0.03 * soft4 + 0.05 * soft + 0.03 * hard_cut)

                elif section_id == "S3":
                    u = section_u("S3", st)
                    accent01 = get_control_value(S3_CTRL, "accent_strength", u)
                    drive = get_control_value(S3_CTRL, "phrase_drive", u)
                    vel += s3_velocity_delta_from_accent(accent01, S3_VEL_GAIN_BASS)
                    en = st + (eighth * 0.84) * s3_duration_scale(drive)

                add_note(piano, note, st, en, vel)

    # Strings
    add_string_parts(
        vn1=vn1,
        vn2=vn2,
        va=va,
        vc=vc,
        chord_name=chord_name,
        triad_voiced=triad,
        bar_start=t,
        bar_dur=bar_dur,
        feature_row=row,
        dyn=dyn,
        bar_global_index=i,
        s1_ctrl=S1_CTRL,
        s1_state=S1_STATE,
        s2_ctrl=S2_CTRL,
        s2_state=S2_STATE,
        s3_ctrl=S3_CTRL,
        s3_state=S3_STATE,
    )

    # Section drums
    if section_id == "S1":
        add_s1_drum_parts(drums, t, bar_dur, S1_CTRL)
    elif section_id == "S3":
        add_s3_drum_parts(drums, t, bar_dur, S3_CTRL)
    elif section_id == "S5":
        add_s5_drum_parts(drums, t, bar_dur, S5_CTRL)

    t += bar_dur


# =========================================================
# 最後の余韻
# =========================================================
final_bpm = SECTIONS[-1]["bpm"]
final_bar_dur = (60.0 / final_bpm) * BEATS_PER_BAR
tail_start = t
tail_len = final_bar_dur * 1.8

for p in [69, 73, 76]:
    add_note(piano, p, tail_start, tail_start + tail_len, 34)

add_note(vn1, 76, tail_start, tail_start + tail_len * 1.02, 40)
add_note(vn2, 73, tail_start, tail_start + tail_len * 0.92, 28)
add_note(va,  69, tail_start, tail_start + tail_len * 0.88, 26)
add_note(vc,  45, tail_start, tail_start + tail_len * 1.00, 30)

pm.instruments.extend([piano, vn1, vn2, va, vc, drums])
pm.write(str(MIDI_OUT))
print(f"[OK] MIDI created: {MIDI_OUT}")


# =========================================================
# MIDI -> WAV
# =========================================================
if not FLUIDSYNTH.exists():
    raise FileNotFoundError(f"fluidsynth.exe not found: {FLUIDSYNTH}")
if not SOUNDFONT.exists():
    raise FileNotFoundError(f"SoundFont not found: {SOUNDFONT}")
if not MIDI_OUT.exists():
    raise FileNotFoundError(f"MIDI not found: {MIDI_OUT}")

def run_fluidsynth(use_ni: bool) -> subprocess.CompletedProcess:
    cmd = [str(FLUIDSYNTH), "-g", "0.8"]
    if use_ni:
        cmd += ["-ni"]
    cmd += ["-F", str(WAV_OUT), "-T", "wav", "-r", "44100", str(SOUNDFONT), str(MIDI_OUT)]
    print("[INFO] Running:", " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True)

p = run_fluidsynth(use_ni=True)

if (p.returncode != 0) or (not WAV_OUT.exists()) or (WAV_OUT.exists() and WAV_OUT.stat().st_size < 1000):
    if p.stdout.strip():
        print(p.stdout)
    if p.stderr.strip():
        print(p.stderr)
    print("[WARN] Retrying without -ni ...")
    p = run_fluidsynth(use_ni=False)

if p.stdout.strip():
    print(p.stdout)
if p.stderr.strip():
    print(p.stderr)

if WAV_OUT.exists() and WAV_OUT.stat().st_size > 1000:
    print(f"[OK] WAV created: {WAV_OUT}")
else:
    raise RuntimeError("WAV was not created. See FluidSynth output above.")