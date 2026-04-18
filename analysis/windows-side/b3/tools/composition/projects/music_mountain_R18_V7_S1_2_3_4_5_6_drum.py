import pretty_midi
import subprocess
from pathlib import Path
import random
import pandas as pd
import numpy as np

# =========================
# 基本設定
# =========================
BEATS_PER_BAR = 4

BASE_DIR = Path(__file__).resolve().parent
MIDI_OUT = (BASE_DIR / "toyota_R18_S1_2_3_4_5_6_drum.mid").resolve()
WAV_OUT  = (BASE_DIR / "toyota_R18_S1_2_3_4_5_6_drum.wav").resolve()

FLUIDSYNTH = Path(r"C:\fluidsynth\bin\fluidsynth.exe").resolve()
SOUNDFONT  = Path(r"C:\FluidR3_GM\FluidR3_GM.sf2").resolve()

SECTION_XLSX = Path(
    r"D:\701lab\work\phaseB\analysis\b3\section\by_run\run_20260412_094452_386655\run_20260412_094452_386655.xlsx"
).resolve()

SESSION_CSV = Path(
    r"D:\701lab\work\phaseB\analysis\b3\session_timeseries\by_run\run_20260412_094452_386655\run_20260412_094452_386655_session_timeseries.csv"
).resolve()

RANDOM_SEED = 7

S1_DETAIL_CSV = Path(
    r"D:\701lab\work\phaseB\analysis\b3\session_timeseries\by_run\run_20260412_094452_386655\run_20260412_094452_386655_S1_timeseries.csv"
).resolve()

S2_DETAIL_CSV = Path(
    r"D:\701lab\work\phaseB\analysis\b3\session_timeseries\by_run\run_20260412_094452_386655\run_20260412_094452_386655_S2_timeseries.csv"
).resolve()

S3_DETAIL_CSV = Path(
    r"D:\701lab\work\phaseB\analysis\b3\session_timeseries\by_run\run_20260412_094452_386655\run_20260412_094452_386655_S3_timeseries.csv"
).resolve()

S4_DETAIL_CSV = Path(
    r"D:\701lab\work\phaseB\analysis\b3\session_timeseries\by_run\run_20260412_094452_386655\run_20260412_094452_386655_S4_timeseries.csv"
).resolve()

S5_DETAIL_CSV = Path(
    r"D:\701lab\work\phaseB\analysis\b3\session_timeseries\by_run\run_20260412_094452_386655\run_20260412_094452_386655_S5_timeseries.csv"
).resolve()

S6_DETAIL_CSV = Path(
    r"D:\701lab\work\phaseB\analysis\b3\session_timeseries\by_run\run_20260412_094452_386655\run_20260412_094452_386655_S6_timeseries.csv"
).resolve()

# =========================
# セクションごとの小節数
# =========================
SECTION_BARS = {
    "S1": 18,
    "S2": 18,
    "S3": 18,
    "S4": 20,
    "S5": 20,
    "S6": 24,
}

SECTION_ORDER = ["S1", "S2", "S3", "S4", "S5", "S6"]

# =========================
# コード定義
# =========================
CHORD_TONES = {
    "C":      [60, 64, 67],
    "G/B":    [59, 62, 67],
    "Am":     [57, 60, 64],
    "Em/G":   [55, 59, 64],
    "F":      [53, 57, 60],
    "C/E":    [64, 67, 72],
    "Dm7":    [50, 53, 57, 60],
    "G7":     [55, 59, 62, 65],
    "Am/G":   [55, 57, 60, 64],
    "Em":     [52, 55, 59],
    "E7":     [52, 56, 59, 62],
    "D7":     [50, 54, 57, 60],
    "G":      [55, 59, 62],
    "C/G":    [55, 60, 64],
    "Dm":     [50, 53, 57],
    "A7":     [57, 61, 64, 67],
    "Am/C":   [48, 57, 60, 64],
    "Bdim7":  [59, 62, 65, 68],
    "E7/G#":  [56, 59, 62, 64],
    "D/F#":   [54, 57, 62],
}

# =========================
# セクション進行
# =========================
S1 = [
    "C", "G/B", "Am", "Em/G",
    "F", "C/E", "Dm7", "G7",
    "C", "G/B", "Am", "C/G",
    "F", "Em", "Dm7", "G7",
    "F G", "C",
]

S2 = [
    "C", "G/B", "Am", "Am/G",
    "F", "Em",
    "Dm7", "G7",
    "C", "G/B", "Am", "Am/G",
    "F", "Em",
    "Dm7", "G7",
    "Am D7", "G",
]

S3 = [
    "C", "G/B", "Am", "C/G",
    "F", "C/E",
    "Dm", "A7",
    "Dm", "G7",
    "Em", "Am",
    "Dm", "G7",
    "Em Am", "Dm G",
    "F G", "C",
]

S4 = [
    "Am", "Em/G", "F", "C/E",
    "Dm", "Am/C",
    "Bdim7", "E7",
    "Am", "Em/G", "F", "C/E",
    "Dm", "Am/C",
    "Bdim7", "E7",
    "Am", "G",
    "F G", "C",
]

S5 = [
    # 前半8小節
    "C", "G/B", "Am", "E7/G#",
    "Am/G", "D/F#",
    "F", "G",

    # 繰り返しは最初の2小節だけ
    "C", "G/B",

    # 元の後半10小節
    "Em", "Am",
    "Dm7", "G7",
    "C", "G/B",
    "Am", "E7/G#",
    "Dm7 G7", "C",
]

S6 = [
    "C", "C/E", "F", "G",
    "Em", "Am",
    "Dm", "G7",

    "C", "Am",
    "F", "G",
    "Em", "Am",
    "Dm", "G7",

    "C", "Am",
    "Dm", "G7",
    "Em", "Am",
    "G7", "C",
]

SECTIONS = {
    "S1": S1,
    "S2": S2,
    "S3": S3,
    "S4": S4,
    "S5": S5,
    "S6": S6,
}

# =========================
# 便利関数
# =========================
def add_note(inst, pitch, start, end, vel):
    if end <= start:
        return
    inst.notes.append(
        pretty_midi.Note(
            velocity=int(max(1, min(127, vel))),
            pitch=int(pitch),
            start=float(start),
            end=float(end),
        )
    )

def build_s1_expression_context(csv_path: Path):
    if not csv_path.exists():
        print(f"[WARN] S1 detail csv not found: {csv_path}")
        return None

    df = pd.read_csv(csv_path)

    req = ["t_rel_sec", "ax_g_s", "ay_g_s", "gz_dps_s", "d_speed_kmh_dt"]
    for c in req:
        if c not in df.columns:
            raise RuntimeError(f"S1 detail csv missing column: {c}")
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.sort_values("t_rel_sec").reset_index(drop=True)

    df["drive_proxy"] = df["d_speed_kmh_dt"].fillna(0.0) + 0.7 * df["ax_g_s"].fillna(0.0)
    df["activity_proxy"] = np.abs(df["ay_g_s"].fillna(0.0)) + 0.8 * np.abs(df["gz_dps_s"].fillna(0.0))

    dur = float(df["t_rel_sec"].max())
    if dur <= 0:
        return None

    return {
        "duration_sec": dur,
        "drive_q50": float(df["drive_proxy"].quantile(0.50)),
        "drive_q80": float(df["drive_proxy"].quantile(0.80)),
        "activity_q50": float(df["activity_proxy"].quantile(0.50)),
        "activity_q80": float(df["activity_proxy"].quantile(0.80)),
    }

def s1_window_features(sec_df: pd.DataFrame, t0: float, t1: float):
    d = sec_df[(sec_df["t_rel_sec"] >= t0) & (sec_df["t_rel_sec"] < t1)]
    if d.empty:
        return {
            "drive": 0.0,
            "activity": 0.0,
        }

    drive = safe_mean(d["d_speed_kmh_dt"], 0.0) + 0.7 * safe_mean(d["ax_g_s"], 0.0)
    activity = safe_abs_mean(d["ay_g_s"], 0.0) + 0.8 * safe_abs_mean(d["gz_dps_s"], 0.0)
    return {
        "drive": drive,
        "activity": activity,
    }

def norm_by_quantiles(x, q50, q80):
    if q80 <= q50 + 1e-9:
        return 0.0
    return clamp((x - q50) / (q80 - q50), 0.0, 1.0)

def add_control_change(inst, number, value, time_sec):
    value = int(clamp(round(value), 0, 127))
    inst.control_changes.append(
        pretty_midi.ControlChange(number=int(number), value=value, time=float(time_sec))
    )

def add_pitch_bend(inst, value, time_sec):
    value = int(clamp(round(value), -8192, 8191))
    inst.pitch_bends.append(
        pretty_midi.PitchBend(pitch=value, time=float(time_sec))
    )

def add_subtle_vibrato(inst, note_start, note_end, depth=180, hz=5.2):
    dur = note_end - note_start
    if dur < 0.55:
        return

    vib_start = note_start + dur * 0.38
    vib_end = note_end - dur * 0.10
    if vib_end <= vib_start:
        return

    times = np.arange(vib_start, vib_end, 1.0 / 24.0)
    for t in times:
        phase = 2.0 * np.pi * hz * (t - vib_start)
        bend = depth * np.sin(phase)
        add_pitch_bend(inst, bend, t)

    add_pitch_bend(inst, 0, vib_end + 0.01)

def add_s1_right_hand_color(piano_inst, chord_name, bar_start_music, note_start, note_end, seconds_per_beat, richness):
    dur = note_end - note_start
    if dur < seconds_per_beat * 0.95:
        return

    pcs = chord_pitch_classes(chord_name)
    pool = melodic_pool_from_pcs(pcs, lo=67, hi=79)
    if not pool:
        return

    center = nearest_pitch(72, pool)

    st = note_start + dur * 0.46
    en = min(note_end, st + seconds_per_beat * (0.58 + 0.24 * richness))
    if en <= st:
        return

    add_note(
        piano_inst,
        pitch=center,
        start=humanize(st, 0.002),
        end=humanize(en, 0.002),
        vel=int(36 + 12 * richness)
    )

    if richness > 0.30:
        upper_candidates = [p for p in pool if p > center]
        if upper_candidates:
            upper = upper_candidates[0]
            add_note(
                piano_inst,
                pitch=upper,
                start=humanize(st + 0.01, 0.002),
                end=humanize(en, 0.002),
                vel=int(30 + 8 * richness)
            )

def add_s2_right_hand_color(piano_inst, chord_name, note_start, note_end, seconds_per_beat, richness):
    dur = note_end - note_start
    if dur < seconds_per_beat * 0.70:
        return

    pcs = chord_pitch_classes(chord_name)
    pool = melodic_pool_from_pcs(pcs, lo=67, hi=81)
    if not pool:
        return

    center = nearest_pitch(74, pool)

    st = note_start + dur * 0.36
    en = min(note_end, st + seconds_per_beat * (0.72 + 0.26 * richness))
    if en <= st:
        return

    add_note(
        piano_inst,
        pitch=center,
        start=humanize(st, 0.002),
        end=humanize(en, 0.002),
        vel=int(40 + 14 * richness)
    )

    if richness > 0.18:
        upper_candidates = [p for p in pool if p > center]
        if upper_candidates:
            upper = upper_candidates[0]
            add_note(
                piano_inst,
                pitch=upper,
                start=humanize(st + 0.01, 0.002),
                end=humanize(en, 0.002),
                vel=int(32 + 10 * richness)
            )

    if richness > 0.55:
        tail_candidates = [p for p in pool if abs(p - center) <= 4 and p != center]
        if tail_candidates:
            tail = tail_candidates[0]
            st2 = max(note_start, note_end - seconds_per_beat * 0.34)
            en2 = min(note_end, st2 + seconds_per_beat * 0.22)
            if en2 > st2:
                add_note(
                    piano_inst,
                    pitch=tail,
                    start=humanize(st2, 0.002),
                    end=humanize(en2, 0.002),
                    vel=int(28 + 8 * richness)
                )

def add_s3_right_hand_color(piano_inst, chord_name, note_start, note_end, seconds_per_beat, richness):
    dur = note_end - note_start
    if dur < seconds_per_beat * 0.62:
        return

    pcs = chord_pitch_classes(chord_name)
    pool = melodic_pool_from_pcs(pcs, lo=68, hi=82)
    if not pool:
        return

    center = nearest_pitch(74, pool)

    st = note_start + dur * 0.30
    en = min(note_end, st + seconds_per_beat * (0.86 + 0.30 * richness))
    if en <= st:
        return

    add_note(
        piano_inst,
        pitch=center,
        start=humanize(st, 0.002),
        end=humanize(en, 0.002),
        vel=int(42 + 14 * richness)
    )

    if richness > 0.14:
        upper_candidates = [p for p in pool if p > center]
        if upper_candidates:
            upper = upper_candidates[0]
            add_note(
                piano_inst,
                pitch=upper,
                start=humanize(st + 0.008, 0.002),
                end=humanize(en, 0.002),
                vel=int(34 + 10 * richness)
            )

    if richness > 0.50:
        tail_candidates = [p for p in pool if abs(p - center) <= 5 and p != center]
        if tail_candidates:
            tail = tail_candidates[0]
            st2 = max(note_start, note_end - seconds_per_beat * 0.42)
            en2 = min(note_end, st2 + seconds_per_beat * 0.26)
            if en2 > st2:
                add_note(
                    piano_inst,
                    pitch=tail,
                    start=humanize(st2, 0.002),
                    end=humanize(en2, 0.002),
                    vel=int(30 + 8 * richness)
                )

def add_s5_right_hand_color(piano_inst, chord_name, note_start, note_end, seconds_per_beat, richness):
    dur = note_end - note_start
    if dur < seconds_per_beat * 0.60:
        return

    pcs = chord_pitch_classes(chord_name)
    pool = melodic_pool_from_pcs(pcs, lo=67, hi=81)
    if not pool:
        return

    center = nearest_pitch(73, pool)

    st = note_start + dur * 0.34
    en = min(note_end, st + seconds_per_beat * (0.74 + 0.24 * richness))
    if en <= st:
        return

    add_note(
        piano_inst,
        pitch=center,
        start=humanize(st, 0.002),
        end=humanize(en, 0.002),
        vel=int(40 + 13 * richness)
    )

    if richness > 0.20:
        upper_candidates = [p for p in pool if p > center]
        if upper_candidates:
            upper = upper_candidates[0]
            add_note(
                piano_inst,
                pitch=upper,
                start=humanize(st + 0.01, 0.002),
                end=humanize(en, 0.002),
                vel=int(31 + 9 * richness)
            )

    if richness > 0.56:
        tail_candidates = [p for p in pool if abs(p - center) <= 4 and p != center]
        if tail_candidates:
            tail = tail_candidates[0]
            st2 = max(note_start, note_end - seconds_per_beat * 0.30)
            en2 = min(note_end, st2 + seconds_per_beat * 0.20)
            if en2 > st2:
                add_note(
                    piano_inst,
                    pitch=tail,
                    start=humanize(st2, 0.002),
                    end=humanize(en2, 0.002),
                    vel=int(28 + 7 * richness)
                )

def voiced_with_optional_color(chord_name, richness, threshold=0.38):
    voiced = piano_left_voicing(chord_name)

    if richness > threshold:
        tones = sorted(get_chord_tones(chord_name))
        top = max(tones)
        q = top - 12
        while q < 48:
            q += 12
        while q > 67:
            q -= 12
        voiced = sorted(set(voiced + [q]))

    return voiced

def humanize(t, amount=0.003):
    return t + random.uniform(-amount, amount)

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def split_bar_chords(chord_text: str):
    return chord_text.strip().split()

def get_chord_tones(chord_name: str):
    if chord_name not in CHORD_TONES:
        raise KeyError(f"Chord not defined: {chord_name}")
    return CHORD_TONES[chord_name]

def chord_pitch_classes(chord_name: str):
    return sorted({p % 12 for p in get_chord_tones(chord_name)})

def nearest_pitch(target, candidates):
    return min(candidates, key=lambda x: abs(x - target))

def melodic_pool_from_pcs(pcs, lo=55, hi=76):
    return [p for p in range(lo, hi + 1) if (p % 12) in pcs]

def piano_left_voicing(chord_name: str):
    tones = sorted(get_chord_tones(chord_name))
    voiced = []
    for p in tones:
        q = p - 12
        while q > 64:
            q -= 12
        while q < 36:
            q += 12
        voiced.append(q)
    return sorted(set(voiced))

def safe_mean(series, default=0.0):
    arr = pd.to_numeric(series, errors="coerce").dropna()
    return float(arr.mean()) if len(arr) else default

def safe_abs_mean(series, default=0.0):
    arr = pd.to_numeric(series, errors="coerce").dropna()
    return float(np.abs(arr).mean()) if len(arr) else default

def zscore_or_zero(x, mean, std):
    return 0.0 if (std is None or std <= 1e-12) else (x - mean) / std

def merge_same_pitch_events(events, gap_tolerance=0.03):
    if not events:
        return []

    events = sorted(events, key=lambda e: e["start"])
    merged = [events[0].copy()]
    merged[0]["merged"] = False
    merged[0]["source"] = "cello"

    for ev in events[1:]:
        last = merged[-1]
        if ev["pitch"] == last["pitch"] and (ev["start"] - last["end"]) <= gap_tolerance:
            last["end"] = max(last["end"], ev["end"])
            last["vel"] = int(round((last["vel"] + ev["vel"]) / 2))
            last["merged"] = True
        else:
            new_ev = ev.copy()
            new_ev["merged"] = False
            new_ev["source"] = "cello"
            merged.append(new_ev)

    return merged

def apply_handoff_after_merged(events):
    if not events:
        return []

    out = []
    handoff_next = False
    for ev in events:
        cur = ev.copy()
        cur["source"] = "piano" if handoff_next else "cello"
        handoff_next = False
        out.append(cur)
        if cur.get("merged", False):
            handoff_next = True
    return out

def transform_repeated_phrase_events(events, chord_name):
    if not events:
        return []

    pcs = chord_pitch_classes(chord_name)
    melodic_pool = melodic_pool_from_pcs(pcs, lo=50, hi=78)

    out = []
    for i, ev in enumerate(sorted(events, key=lambda e: e["start"])):
        new_ev = ev.copy()

        if i % 3 == 1 and melodic_pool:
            new_ev["pitch"] = nearest_pitch(new_ev["pitch"], melodic_pool)

        if i % 4 == 2:
            dur = new_ev["end"] - new_ev["start"]
            new_ev["end"] = new_ev["start"] + dur * 1.15

        out.append(new_ev)

    return out

def extend_s5_tail_on_cello(recalled_events, bar_duration, seconds_per_beat, bar_idx):
    if not recalled_events:
        return recalled_events

    events = sorted([ev.copy() for ev in recalled_events], key=lambda e: e["end"])

    last_idx = None
    for i in range(len(events) - 1, -1, -1):
        if events[i].get("source") == "cello":
            last_idx = i
            break

    if last_idx is None:
        return events

    last_ev = events[last_idx]
    tail_gap = bar_duration - last_ev["end"]

    if tail_gap < seconds_per_beat * 0.20:
        return events

    if bar_idx <= 4:
        new_end = bar_duration + seconds_per_beat * 0.005
    else:
        new_end = min(
            bar_duration + seconds_per_beat * 0.05,
            last_ev["end"] + seconds_per_beat * 1.10
        )

    if new_end > last_ev["end"]:
        events[last_idx]["end"] = new_end

    return events

def reinforce_s5_bars_6_7_on_cello(recalled_events, chord_name, bar_idx, seconds_per_beat):
    if bar_idx not in (5, 6):
        return recalled_events

    events = [ev.copy() for ev in recalled_events]

    pcs = chord_pitch_classes(chord_name)
    pool = melodic_pool_from_pcs(pcs, lo=55, hi=74)
    if not pool:
        return events

    last_cello_pitch = None
    for ev in reversed(events):
        if ev.get("source") == "cello":
            last_cello_pitch = ev["pitch"]
            break

    if last_cello_pitch is None:
        last_cello_pitch = nearest_pitch(64, pool)

    p1 = nearest_pitch(last_cello_pitch, pool)
    p2_candidates = [p for p in pool if abs(p - p1) <= 4 and p != p1]
    p2 = p2_candidates[0] if p2_candidates else p1

    events.append({
        "source": "cello",
        "pitch": p1,
        "start": seconds_per_beat * 2.0,
        "end": seconds_per_beat * 2.85,
        "vel": 76,
    })
    events.append({
        "source": "cello",
        "pitch": p2,
        "start": seconds_per_beat * 3.0,
        "end": seconds_per_beat * 3.90,
        "vel": 72,
    })

    return sorted(events, key=lambda e: e["start"])

def add_s4_piano_response(
    piano_inst,
    chord_name,
    cello_events,
    bar_start_music,
    seconds_per_beat,
    sec_df=None,
    bar_start_data=None,
    bar_duration_data=None,
    s4_expr_ctx=None,
):
    if not cello_events:
        return

    pcs = chord_pitch_classes(chord_name)
    rh_pool = melodic_pool_from_pcs(pcs, lo=56, hi=74)
    if not rh_pool:
        return

    drive_norm = 0.0
    activity_norm = 0.0
    richness = 0.0

    if sec_df is not None and bar_start_data is not None and bar_duration_data is not None and s4_expr_ctx is not None:
        feats = s1_window_features(sec_df, bar_start_data, bar_start_data + bar_duration_data)
        drive_norm = norm_by_quantiles(
            feats["drive"], s4_expr_ctx["drive_q50"], s4_expr_ctx["drive_q80"]
        )
        activity_norm = norm_by_quantiles(
            feats["activity"], s4_expr_ctx["activity_q50"], s4_expr_ctx["activity_q80"]
        )
        richness = clamp(0.42 + 0.22 * activity_norm + 0.30 * drive_norm, 0.0, 1.0)

    for ev in cello_events:
        dur = ev["end"] - ev["start"]
        if dur < seconds_per_beat * 0.82:
            continue

        response_start = ev["start"] + dur * (0.44 - 0.04 * richness)
        response_end = min(ev["end"], ev["start"] + seconds_per_beat * (1.35 + 0.20 * richness))
        if response_end <= response_start:
            continue

        note_count = 2 if richness < 0.45 else 3
        span = response_end - response_start
        unit = span / note_count

        base_pitch = nearest_pitch(ev["pitch"], rh_pool)
        prev_pitch = base_pitch

        for j in range(note_count):
            st = bar_start_music + response_start + j * unit
            en = st + unit * (0.90 if note_count == 2 else 0.84)

            candidates = [p for p in rh_pool if abs(p - prev_pitch) <= 4]
            if not candidates:
                candidates = rh_pool[:]

            pitch = nearest_pitch(base_pitch if j == 0 else prev_pitch, candidates)

            vel = int(clamp(46 + 8 * richness - j * 2, 38, 64))

            add_note(
                piano_inst,
                pitch=pitch,
                start=humanize(st, 0.002),
                end=humanize(en, 0.002),
                vel=vel
            )
            prev_pitch = pitch

def add_s6_piano_response_like_s1(
    piano_inst,
    chord_name,
    bar_idx,
    bar_start_music,
    seconds_per_beat,
    sub_dur_music,
    prev_rh_pitch_holder,
    sec_df=None,
    bar_start_data=None,
    bar_duration_data=None,
    s6_expr_ctx=None,
    phrase_mode="normal",
):
    pcs = chord_pitch_classes(chord_name)
    rh_pool = melodic_pool_from_pcs(pcs, lo=60, hi=79)
    if not rh_pool:
        return prev_rh_pitch_holder

    drive_norm = 0.0
    activity_norm = 0.0
    richness = 0.0

    if sec_df is not None and bar_start_data is not None and bar_duration_data is not None and s6_expr_ctx is not None:
        feats = s1_window_features(sec_df, bar_start_data, bar_start_data + bar_duration_data)
        drive_norm = norm_by_quantiles(
            feats["drive"], s6_expr_ctx["drive_q50"], s6_expr_ctx["drive_q80"]
        )
        activity_norm = norm_by_quantiles(
            feats["activity"], s6_expr_ctx["activity_q50"], s6_expr_ctx["activity_q80"]
        )
        richness = clamp(0.28 + 0.18 * activity_norm + 0.22 * drive_norm, 0.0, 1.0)

    prev_rh = prev_rh_pitch_holder

    if phrase_mode == "coda":
        pattern_type = 0
    elif phrase_mode == "s6_descent":
        pattern_type = 1
    else:
        pattern_type = bar_idx % 4

    if pattern_type == 0:
        pitch = nearest_pitch(prev_rh, rh_pool)
        st = bar_start_music + seconds_per_beat * (0.7 if phrase_mode == "coda" else 0.6)
        en = min(bar_start_music + sub_dur_music, st + seconds_per_beat * (1.5 + 0.2 * richness))
        add_note(piano_inst, pitch, humanize(st, 0.003), humanize(en, 0.003), vel=int(40 + 4 * richness))
        prev_rh = pitch

    elif pattern_type == 1:
        pitch = nearest_pitch(prev_rh, rh_pool)
        st = bar_start_music + seconds_per_beat * 1.0
        en = min(bar_start_music + sub_dur_music, st + seconds_per_beat * (1.2 + 0.15 * richness))
        add_note(piano_inst, pitch, humanize(st, 0.003), humanize(en, 0.003), vel=int(38 + 4 * richness))
        prev_rh = pitch

    elif pattern_type == 2 and phrase_mode not in ("s6_descent", "coda"):
        pitch = nearest_pitch(prev_rh, rh_pool)
        st = bar_start_music + seconds_per_beat * 0.8
        en = st + seconds_per_beat * (1.1 + 0.15 * richness)
        en = min(bar_start_music + sub_dur_music - 0.10, en)
        add_note(piano_inst, pitch, humanize(st, 0.003), humanize(en, 0.003), vel=int(38 + 3 * richness))

        if richness > 0.35:
            tail_candidates = [p for p in rh_pool if abs(p - pitch) <= 4 and p != pitch]
            tail_pitch = tail_candidates[0] if tail_candidates else pitch
            st2 = bar_start_music + sub_dur_music - seconds_per_beat * 0.40
            en2 = st2 + seconds_per_beat * 0.24
            add_note(piano_inst, tail_pitch, humanize(st2, 0.003), humanize(en2, 0.003), vel=32)
            prev_rh = tail_pitch
        else:
            prev_rh = pitch

    else:
        chosen = rh_pool[:2] if len(rh_pool) >= 2 else rh_pool

        if phrase_mode == "coda":
            chosen = chosen[:1]

        st = bar_start_music + seconds_per_beat * 1.0
        en = min(bar_start_music + sub_dur_music, st + seconds_per_beat * (1.2 + 0.1 * richness))
        for k, p in enumerate(chosen):
            add_note(
                piano_inst,
                p,
                humanize(st + 0.01 * k, 0.003),
                humanize(en, 0.003),
                vel=int(36 + 3 * richness) - k * 4
            )
        prev_rh = chosen[0]

    return prev_rh

# =========================
# ドラム用関数
# =========================
def drum_window_features(sec_df: pd.DataFrame, t0: float, t1: float):
    d = sec_df[(sec_df["t_rel_sec"] >= t0) & (sec_df["t_rel_sec"] < t1)]
    if d.empty:
        return {
            "drive": 0.0,
            "sway": 0.0,
            "settle": 0.0,
        }

    drive = safe_mean(d["d_speed_kmh_dt"], 0.0) + 0.7 * safe_mean(d["ax_g_s"], 0.0)

    sway = (
        0.9 * safe_abs_mean(d["ay_g_s"], 0.0)
        + 1.0 * safe_abs_mean(d["gz_dps_s"], 0.0)
    )

    if "roll_deg_s" in d.columns:
        sway += 0.25 * safe_abs_mean(d["roll_deg_s"], 0.0)

    if len(d) >= 2:
        sway_series = (
            0.9 * pd.to_numeric(d["ay_g_s"], errors="coerce").abs().fillna(0.0)
            + 1.0 * pd.to_numeric(d["gz_dps_s"], errors="coerce").abs().fillna(0.0)
        )
        settle = float(np.abs(np.diff(sway_series.values)).mean()) if len(sway_series) >= 2 else 0.0
    else:
        settle = 0.0

    return {
        "drive": drive,
        "sway": sway,
        "settle": settle,
    }

def build_drum_feature_stats(df):
    stats = {}
    for sec_name in SECTION_ORDER:
        dsec = df[df["session_id"] == sec_name].copy()
        if dsec.empty:
            raise RuntimeError(f"No rows found for session_id={sec_name} in csv")

        drive = dsec["d_speed_kmh_dt"].fillna(0.0) + 0.7 * dsec["ax_g_s"].fillna(0.0)
        sway = (
            0.9 * dsec["ay_g_s"].abs().fillna(0.0)
            + 1.0 * dsec["gz_dps_s"].abs().fillna(0.0)
        )
        if "roll_deg_s" in dsec.columns:
            sway = sway + 0.25 * dsec["roll_deg_s"].abs().fillna(0.0)

        if len(dsec) >= 2:
            settle = np.abs(np.diff(sway.values))
            settle_mean = float(np.mean(settle)) if len(settle) else 0.0
            settle_std = float(np.std(settle)) if len(settle) else 0.0
        else:
            settle_mean = 0.0
            settle_std = 0.0

        stats[sec_name] = {
            "drive_mean": float(drive.mean()),
            "drive_std": float(drive.std(ddof=0)) if len(dsec) > 1 else 0.0,
            "sway_mean": float(sway.mean()),
            "sway_std": float(sway.std(ddof=0)) if len(dsec) > 1 else 0.0,
            "settle_mean": settle_mean,
            "settle_std": settle_std,
        }
    return stats

def add_r18_drum_layer_for_subchord(
    drum_inst,
    sec_df: pd.DataFrame,
    sec_name: str,
    sub_start_music: float,
    sub_dur_music: float,
    sub_start_data: float,
    sub_dur_data: float,
    seconds_per_beat: float,
    drum_stats: dict,
    phrase_mode: str = "normal",
):
    """
    まずは底流としての「どっどっどっど」だけ入れる版。
    - 各拍頭にキック
    - drive で少しだけ強弱
    - 余計なタムや後打ちは入れない
    """
    beat_count = int(round(sub_dur_music / seconds_per_beat))
    if beat_count <= 0:
        return

    sec_stat = drum_stats[sec_name]

    for beat_idx in range(beat_count):
        beat_start_music = sub_start_music + beat_idx * seconds_per_beat
        beat_start_data = sub_start_data + beat_idx * (sub_dur_data / beat_count)
        beat_end_data = beat_start_data + (sub_dur_data / beat_count)

        feats = drum_window_features(sec_df, beat_start_data, beat_end_data)
        drive_z = zscore_or_zero(feats["drive"], sec_stat["drive_mean"], sec_stat["drive_std"])

        # 基本の太さ
        if sec_name == "S1":
            base_kick = 56
        elif sec_name == "S2":
            base_kick = 58
        elif sec_name == "S3":
            base_kick = 60
        elif sec_name == "S4":
            base_kick = 60
        elif sec_name == "S5":
            base_kick = 61
        else:  # S6
            if phrase_mode == "coda":
                base_kick = 52
            elif phrase_mode == "s6_descent":
                base_kick = 56
            else:
                base_kick = 58

        # 強弱は最小限
        kick_vel = int(clamp(base_kick + 4 * drive_z, 44, 76))

        # S6終盤だけ少し整理
        if sec_name == "S6":
            if phrase_mode == "s6_descent":
                kick_vel = int(clamp(kick_vel - 2, 42, 72))
            elif phrase_mode == "coda":
                kick_vel = int(clamp(kick_vel - 6, 38, 66))

        add_note(
            drum_inst,
            pitch=36,  # Bass Drum 1
            start=humanize(beat_start_music, 0.0010),
            end=beat_start_music + seconds_per_beat * 0.09,
            vel=kick_vel,
        )

# =========================
# 区間BPM読み込み
# =========================
def read_section_timings_and_bpms(xlsx_path: Path):
    if not xlsx_path.exists():
        raise FileNotFoundError(f"Section xlsx not found: {xlsx_path}")

    df = pd.read_excel(xlsx_path)
    if df.empty:
        raise RuntimeError("Section xlsx is empty.")

    header_row = df.iloc[0].tolist()
    data = df.iloc[1:].copy()
    data.columns = header_row

    required_cols = {"GPS_time", "start", "end"}
    if not required_cols.issubset(set(data.columns)):
        raise RuntimeError(f"Required columns not found. columns={list(data.columns)}")

    data = data[["GPS_time", "start", "end"]].copy()
    data["GPS_time"] = data["GPS_time"].astype(str).str.strip()
    data["start"] = data["start"].astype(str).str.strip()
    data["end"] = data["end"].astype(str).str.strip()

    result = {}
    for sec_name in SECTION_ORDER:
        row = data[data["GPS_time"] == sec_name]
        if row.empty:
            raise RuntimeError(f"{sec_name} not found in xlsx.")

        start_t = pd.to_datetime(row.iloc[0]["start"], format="%H:%M:%S")
        end_t = pd.to_datetime(row.iloc[0]["end"], format="%H:%M:%S")
        duration_sec = (end_t - start_t).total_seconds()
        if duration_sec <= 0:
            raise RuntimeError(f"{sec_name} duration is not positive: {duration_sec}")

        bars = SECTION_BARS[sec_name]
        beats = bars * BEATS_PER_BAR
        bpm = beats * 60.0 / duration_sec
        seconds_per_beat = 60.0 / bpm
        bar_duration = seconds_per_beat * BEATS_PER_BAR

        result[sec_name] = {
            "start": row.iloc[0]["start"],
            "end": row.iloc[0]["end"],
            "duration_sec": duration_sec,
            "bars": bars,
            "beats": beats,
            "bpm": bpm,
            "seconds_per_beat": seconds_per_beat,
            "bar_duration": bar_duration,
        }

    return result

# =========================
# session_timeseries 読み込み
# =========================
def load_session_timeseries(csv_path: Path):
    if not csv_path.exists():
        raise FileNotFoundError(f"Session csv not found: {csv_path}")

    df = pd.read_csv(csv_path)

    required_cols = {
        "session_id", "t_rel_sec", "speed_kmh",
        "ax_g_s", "ay_g_s", "gz_dps_s",
        "d_speed_kmh_dt"
    }
    missing = required_cols - set(df.columns)
    if missing:
        raise RuntimeError(f"Missing required columns in csv: {sorted(missing)}")

    numeric_cols = [
        "t_rel_sec", "speed_kmh", "hr_bpm", "rr_ms",
        "ax_g", "ay_g", "az_g",
        "ax_g_s", "ay_g_s", "az_g_s",
        "gx_dps", "gy_dps", "gz_dps",
        "gx_dps_s", "gy_dps_s", "gz_dps_s",
        "roll_deg", "pitch_deg", "yaw_deg",
        "roll_deg_s", "pitch_deg_s", "yaw_deg_s",
        "d_pitch_deg_s_dt", "d_yaw_deg_s_dt",
        "d_ax_g_s_dt", "d_ay_g_s_dt", "d_speed_kmh_dt"
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["session_id"] = df["session_id"].astype(str).str.strip()
    return df.sort_values(["session_id", "t_rel_sec"]).reset_index(drop=True)

def build_section_feature_stats(df):
    stats = {}
    for sec_name in SECTION_ORDER:
        dsec = df[df["session_id"] == sec_name].copy()
        if dsec.empty:
            raise RuntimeError(f"No rows found for session_id={sec_name} in csv")

        drive = dsec["d_speed_kmh_dt"].fillna(0.0) + 0.7 * dsec["ax_g_s"].fillna(0.0)
        activity = np.abs(dsec["ay_g_s"].fillna(0.0)) + 0.8 * np.abs(dsec["gz_dps_s"].fillna(0.0))

        stats[sec_name] = {
            "speed_mean": float(dsec["speed_kmh"].mean()),
            "speed_std": float(dsec["speed_kmh"].std(ddof=0)) if len(dsec) > 1 else 0.0,
            "drive_mean": float(drive.mean()),
            "drive_std": float(drive.std(ddof=0)) if len(dsec) > 1 else 0.0,
            "activity_mean": float(activity.mean()),
            "activity_std": float(activity.std(ddof=0)) if len(dsec) > 1 else 0.0,
        }
    return stats

# =========================
# メロディ生成
# =========================
def choose_melody_events_for_beat(
    dbeat: pd.DataFrame,
    sec_name: str,
    chord_name: str,
    prev_pitch: int,
    stats: dict,
    beat_start: float,
    seconds_per_beat: float,
    phrase_mode: str = "normal",
):
    speed_mean = safe_mean(dbeat["speed_kmh"], default=0.0)
    drive_raw = safe_mean(dbeat["d_speed_kmh_dt"], default=0.0) + 0.7 * safe_mean(dbeat["ax_g_s"], default=0.0)
    activity_raw = safe_abs_mean(dbeat["ay_g_s"], default=0.0) + 0.8 * safe_abs_mean(dbeat["gz_dps_s"], default=0.0)

    sec_stats = stats[sec_name]
    speed_z = zscore_or_zero(speed_mean, sec_stats["speed_mean"], sec_stats["speed_std"])
    drive_z = zscore_or_zero(drive_raw, sec_stats["drive_mean"], sec_stats["drive_std"])
    activity_z = zscore_or_zero(activity_raw, sec_stats["activity_mean"], sec_stats["activity_std"])

    if phrase_mode == "coda":
        activity_z -= 0.9
        drive_z *= 0.6
    elif phrase_mode == "s6_bridge":
        activity_z -= 0.35
        drive_z *= 0.8
    elif phrase_mode == "s6_descent":
        activity_z -= 0.2
        drive_z = -abs(drive_z) * 0.8

    pcs = chord_pitch_classes(chord_name)
    base_lo, base_hi = 55, 72
    lo = int(clamp(base_lo + round(speed_z * 2.0), 50, 62))
    hi = int(clamp(base_hi + round(speed_z * 2.0), 67, 78))
    melodic_pool = melodic_pool_from_pcs(pcs, lo=lo, hi=hi)
    if not melodic_pool:
        melodic_pool = melodic_pool_from_pcs(pcs, lo=50, hi=78)

    target = prev_pitch + int(round(drive_z * 2.0))
    if phrase_mode == "s6_descent":
        target = prev_pitch - 2

    candidates = [p for p in melodic_pool if abs(p - target) <= 5] or \
                 [p for p in melodic_pool if abs(p - target) <= 8] or \
                 melodic_pool[:]

    main_pitch = nearest_pitch(target, candidates)
    events = []

    if phrase_mode == "s6_descent":
        second_candidates = [p for p in melodic_pool if p <= main_pitch and p != main_pitch]
        if not second_candidates:
            second_candidates = melodic_pool[:]
        second_pitch = nearest_pitch(main_pitch - 2, second_candidates)

        st1 = beat_start
        en1 = beat_start + seconds_per_beat * 0.44
        st2 = beat_start + seconds_per_beat * 0.52
        en2 = beat_start + seconds_per_beat * 0.96

        events.append({"pitch": main_pitch, "start": st1, "end": en1, "vel": 74})
        events.append({"pitch": second_pitch, "start": st2, "end": en2, "vel": 70})
        return events, second_pitch

    if activity_z > 0.75 and phrase_mode == "normal":
        target2 = main_pitch + int(round(drive_z * 1.5))
        candidates2 = [p for p in melodic_pool if abs(p - target2) <= 4 and p != main_pitch]
        if not candidates2:
            candidates2 = [p for p in melodic_pool if abs(p - main_pitch) <= 5 and p != main_pitch]
        if not candidates2:
            candidates2 = [p for p in melodic_pool if p != main_pitch]
        second_pitch = nearest_pitch(target2, candidates2) if candidates2 else main_pitch

        st1 = beat_start
        en1 = beat_start + seconds_per_beat * 0.46
        st2 = beat_start + seconds_per_beat * 0.50
        en2 = beat_start + seconds_per_beat * 0.96

        vel1 = int(clamp(76 + speed_z * 4 + activity_z * 4, 60, 98))
        vel2 = int(clamp(72 + speed_z * 4 + activity_z * 4, 56, 92))
        events.append({"pitch": main_pitch, "start": st1, "end": en1, "vel": vel1})
        events.append({"pitch": second_pitch, "start": st2, "end": en2, "vel": vel2})
        return events, second_pitch

    sustain_ratio = 0.98 if phrase_mode == "coda" else (0.95 if phrase_mode == "s6_bridge" else (0.92 if speed_z < 0.3 else 0.86))
    en = beat_start + seconds_per_beat * sustain_ratio
    vel = int(clamp(74 + speed_z * 4, 58, 94))
    events.append({"pitch": main_pitch, "start": beat_start, "end": en, "vel": vel})
    return events, main_pitch

def add_data_driven_melody_for_subchord(
    melody_inst,
    piano_inst,
    sec_df: pd.DataFrame,
    sec_name: str,
    chord_name: str,
    sub_start_music: float,
    sub_dur_music: float,
    sub_start_data: float,
    sub_dur_data: float,
    seconds_per_beat: float,
    prev_pitch: int,
    stats: dict,
    phrase_mode: str = "normal",
    s1_expr_ctx = None,
    s2_expr_ctx = None,
    s3_expr_ctx = None,
    s4_expr_ctx = None,
    s5_expr_ctx = None,
    s6_expr_ctx = None,
):
    beat_count = int(round(sub_dur_music / seconds_per_beat))
    if beat_count <= 0:
        return prev_pitch, [], []

    sub_events = []
    for beat_idx in range(beat_count):
        beat_start_music = sub_start_music + beat_idx * seconds_per_beat
        beat_start_data = sub_start_data + beat_idx * (sub_dur_data / beat_count)
        beat_end_data = beat_start_data + (sub_dur_data / beat_count)

        dbeat = sec_df[
            (sec_df["t_rel_sec"] >= beat_start_data) &
            (sec_df["t_rel_sec"] < beat_end_data)
        ]

        beat_events, prev_pitch = choose_melody_events_for_beat(
            dbeat=dbeat,
            sec_name=sec_name,
            chord_name=chord_name,
            prev_pitch=prev_pitch,
            stats=stats,
            beat_start=beat_start_music,
            seconds_per_beat=seconds_per_beat,
            phrase_mode=phrase_mode,
        )
        sub_events.extend(beat_events)

    merged_events = merge_same_pitch_events(sub_events, gap_tolerance=seconds_per_beat * 0.10)
    routed_events = apply_handoff_after_merged(merged_events)

    new_cello_events = []
    for i, ev in enumerate(routed_events):
        next_start = routed_events[i + 1]["start"] if i + 1 < len(routed_events) else None

        if ev["source"] == "cello":
            cello_vel = ev["vel"]

            richness = 0.0
            drive_norm = 0.0
            activity_norm = 0.0
            expr_ctx = None

            if sec_name == "S1" and s1_expr_ctx is not None:
                expr_ctx = s1_expr_ctx
            elif sec_name == "S2" and s2_expr_ctx is not None:
                expr_ctx = s2_expr_ctx
            elif sec_name == "S3" and s3_expr_ctx is not None:
                expr_ctx = s3_expr_ctx
            elif sec_name == "S4" and s4_expr_ctx is not None:
                expr_ctx = s4_expr_ctx
            elif sec_name == "S5" and s5_expr_ctx is not None:
                expr_ctx = s5_expr_ctx
            elif sec_name == "S6" and s6_expr_ctx is not None:
                expr_ctx = s6_expr_ctx

            if expr_ctx is not None:
                feats = s1_window_features(sec_df, sub_start_data, sub_start_data + sub_dur_data)
                drive_norm = norm_by_quantiles(
                    feats["drive"], expr_ctx["drive_q50"], expr_ctx["drive_q80"]
                )
                activity_norm = norm_by_quantiles(
                    feats["activity"], expr_ctx["activity_q50"], expr_ctx["activity_q80"]
                )

                if sec_name == "S1":
                    richness = clamp(0.30 + 0.45 * activity_norm + 0.20 * drive_norm, 0.0, 1.0)
                    cello_vel = int(clamp(cello_vel + 5 * drive_norm - 2 * activity_norm + 5 * richness, 52, 104))
                elif sec_name == "S2":
                    richness = clamp(0.38 + 0.40 * activity_norm + 0.22 * drive_norm, 0.0, 1.0)
                    cello_vel = int(clamp(cello_vel + 6 * drive_norm - 1 * activity_norm + 6 * richness, 52, 108))
                elif sec_name == "S3":
                    richness = clamp(0.46 + 0.34 * activity_norm + 0.26 * drive_norm, 0.0, 1.0)
                    cello_vel = int(clamp(cello_vel + 7 * drive_norm + 6 * richness, 52, 110))
                elif sec_name == "S4":
                    richness = clamp(0.44 + 0.26 * activity_norm + 0.32 * drive_norm, 0.0, 1.0)
                    cello_vel = int(clamp(cello_vel + 8 * drive_norm + 5 * richness - 1 * activity_norm, 52, 112))
                elif sec_name == "S5":
                    richness = clamp(0.40 + 0.32 * activity_norm + 0.30 * drive_norm, 0.0, 1.0)
                    cello_vel = int(clamp(cello_vel + 7 * drive_norm + 6 * richness - 1 * activity_norm, 52, 110))
                elif sec_name == "S6":
                    richness = clamp(0.32 + 0.20 * activity_norm + 0.24 * drive_norm, 0.0, 1.0)

                    if phrase_mode == "coda":
                        richness *= 0.75
                        cello_vel = int(clamp(cello_vel + 3 * drive_norm + 3 * richness - 2, 50, 100))
                    elif phrase_mode == "s6_descent":
                        richness *= 0.85
                        cello_vel = int(clamp(cello_vel + 4 * drive_norm + 3 * richness - 1, 50, 102))
                    else:
                        cello_vel = int(clamp(cello_vel + 5 * drive_norm + 4 * richness - 1 * activity_norm, 50, 104))

            add_note(
                melody_inst,
                pitch=ev["pitch"],
                start=humanize(ev["start"], 0.004),
                end=humanize(ev["end"], 0.004),
                vel=cello_vel
            )
            new_cello_events.append({**ev, "vel": cello_vel})

            if expr_ctx is not None:
                dur = ev["end"] - ev["start"]

                if sec_name == "S1":
                    vib_gate = seconds_per_beat * 0.65
                elif sec_name == "S2":
                    vib_gate = seconds_per_beat * 0.58
                elif sec_name == "S3":
                    vib_gate = seconds_per_beat * 0.52
                elif sec_name == "S4":
                    vib_gate = seconds_per_beat * 0.56
                elif sec_name == "S5":
                    vib_gate = seconds_per_beat * 0.58
                else:  # S6
                    vib_gate = seconds_per_beat * (0.62 if phrase_mode == "coda" else 0.56)

                if dur >= vib_gate:
                    if sec_name == "S1":
                        expr_base = 86 + 14 * drive_norm + 12 * richness
                        expr_dip = 5 * activity_norm
                        vib_depth = 170 + 170 * richness
                        vib_hz = 5.0 + 0.4 * drive_norm
                    elif sec_name == "S2":
                        expr_base = 88 + 15 * drive_norm + 14 * richness
                        expr_dip = 4 * activity_norm
                        vib_depth = 190 + 180 * richness
                        vib_hz = 5.1 + 0.5 * activity_norm
                    elif sec_name == "S3":
                        expr_base = 90 + 16 * drive_norm + 16 * richness
                        expr_dip = 3 * activity_norm
                        vib_depth = 220 + 190 * richness
                        vib_hz = 4.9 + 0.35 * activity_norm
                    elif sec_name == "S4":
                        expr_base = 92 + 17 * drive_norm + 15 * richness
                        expr_dip = 4 * activity_norm
                        vib_depth = 210 + 160 * richness
                        vib_hz = 5.0 + 0.25 * drive_norm
                    elif sec_name == "S5":
                        expr_base = 91 + 15 * drive_norm + 15 * richness
                        expr_dip = 4 * activity_norm
                        vib_depth = 200 + 170 * richness
                        vib_hz = 5.0 + 0.30 * drive_norm
                    else:  # S6
                        if phrase_mode == "coda":
                            expr_base = 84 + 10 * drive_norm + 8 * richness
                            expr_dip = 3 * activity_norm
                            vib_depth = 110 + 90 * richness
                            vib_hz = 4.7
                        elif phrase_mode == "s6_descent":
                            expr_base = 86 + 11 * drive_norm + 9 * richness
                            expr_dip = 3 * activity_norm
                            vib_depth = 130 + 100 * richness
                            vib_hz = 4.8
                        else:
                            expr_base = 88 + 12 * drive_norm + 10 * richness
                            expr_dip = 4 * activity_norm
                            vib_depth = 150 + 120 * richness
                            vib_hz = 4.9

                    add_control_change(melody_inst, 11, expr_base - expr_dip, ev["start"] + dur * 0.04)
                    add_control_change(melody_inst, 11, expr_base + 8, ev["start"] + dur * 0.34)
                    add_control_change(melody_inst, 11, expr_base - 3, ev["end"] - dur * 0.10)

                    add_subtle_vibrato(
                        melody_inst,
                        ev["start"],
                        ev["end"],
                        depth=vib_depth,
                        hz=vib_hz
                    )

                    if sec_name == "S1":
                        add_s1_right_hand_color(
                            piano_inst=piano_inst,
                            chord_name=chord_name,
                            bar_start_music=sub_start_music,
                            note_start=ev["start"],
                            note_end=ev["end"],
                            seconds_per_beat=seconds_per_beat,
                            richness=richness,
                        )
                    elif sec_name == "S2":
                        add_s2_right_hand_color(
                            piano_inst=piano_inst,
                            chord_name=chord_name,
                            note_start=ev["start"],
                            note_end=ev["end"],
                            seconds_per_beat=seconds_per_beat,
                            richness=richness,
                        )
                    elif sec_name == "S3":
                        add_s3_right_hand_color(
                            piano_inst=piano_inst,
                            chord_name=chord_name,
                            note_start=ev["start"],
                            note_end=ev["end"],
                            seconds_per_beat=seconds_per_beat,
                            richness=richness,
                        )
                    elif sec_name == "S5":
                        add_s5_right_hand_color(
                            piano_inst=piano_inst,
                            chord_name=chord_name,
                            note_start=ev["start"],
                            note_end=ev["end"],
                            seconds_per_beat=seconds_per_beat,
                            richness=richness,
                        )

        else:
            piano_start = ev["start"]
            piano_end = ev["end"]
            if next_start is not None:
                piano_end = max(piano_end, next_start - 0.03)
            piano_end = min(piano_end, piano_start + seconds_per_beat * (2.6 if phrase_mode == "coda" else 2.2))

            main_vel = max(48, ev["vel"] - 10)
            add_fifth = True

            if sec_name == "S1" and s1_expr_ctx is not None:
                feats = s1_window_features(sec_df, sub_start_data, sub_start_data + sub_dur_data)
                drive_norm = norm_by_quantiles(
                    feats["drive"], s1_expr_ctx["drive_q50"], s1_expr_ctx["drive_q80"]
                )
                activity_norm = norm_by_quantiles(
                    feats["activity"], s1_expr_ctx["activity_q50"], s1_expr_ctx["activity_q80"]
                )
                richness = clamp(0.30 + 0.45 * activity_norm + 0.20 * drive_norm, 0.0, 1.0)
                main_vel = int(clamp(main_vel + 7 * richness, 42, 90))
                add_fifth = richness > 0.28

            elif sec_name == "S2" and s2_expr_ctx is not None:
                feats = s1_window_features(sec_df, sub_start_data, sub_start_data + sub_dur_data)
                drive_norm = norm_by_quantiles(
                    feats["drive"], s2_expr_ctx["drive_q50"], s2_expr_ctx["drive_q80"]
                )
                activity_norm = norm_by_quantiles(
                    feats["activity"], s2_expr_ctx["activity_q50"], s2_expr_ctx["activity_q80"]
                )
                richness = clamp(0.38 + 0.40 * activity_norm + 0.22 * drive_norm, 0.0, 1.0)
                main_vel = int(clamp(main_vel + 9 * richness, 42, 96))
                add_fifth = richness > 0.18

            elif sec_name == "S3" and s3_expr_ctx is not None:
                feats = s1_window_features(sec_df, sub_start_data, sub_start_data + sub_dur_data)
                drive_norm = norm_by_quantiles(
                    feats["drive"], s3_expr_ctx["drive_q50"], s3_expr_ctx["drive_q80"]
                )
                activity_norm = norm_by_quantiles(
                    feats["activity"], s3_expr_ctx["activity_q50"], s3_expr_ctx["activity_q80"]
                )
                richness = clamp(0.46 + 0.34 * activity_norm + 0.26 * drive_norm, 0.0, 1.0)
                main_vel = int(clamp(main_vel + 10 * richness, 42, 100))
                add_fifth = richness > 0.10

            elif sec_name == "S4" and s4_expr_ctx is not None:
                feats = s1_window_features(sec_df, sub_start_data, sub_start_data + sub_dur_data)
                drive_norm = norm_by_quantiles(
                    feats["drive"], s4_expr_ctx["drive_q50"], s4_expr_ctx["drive_q80"]
                )
                activity_norm = norm_by_quantiles(
                    feats["activity"], s4_expr_ctx["activity_q50"], s4_expr_ctx["activity_q80"]
                )
                richness = clamp(0.44 + 0.26 * activity_norm + 0.32 * drive_norm, 0.0, 1.0)
                main_vel = int(clamp(main_vel + 10 * richness, 42, 102))
                add_fifth = richness > 0.16

            elif sec_name == "S5" and s5_expr_ctx is not None:
                feats = s1_window_features(sec_df, sub_start_data, sub_start_data + sub_dur_data)
                drive_norm = norm_by_quantiles(
                    feats["drive"], s5_expr_ctx["drive_q50"], s5_expr_ctx["drive_q80"]
                )
                activity_norm = norm_by_quantiles(
                    feats["activity"], s5_expr_ctx["activity_q50"], s5_expr_ctx["activity_q80"]
                )
                richness = clamp(0.40 + 0.32 * activity_norm + 0.30 * drive_norm, 0.0, 1.0)
                main_vel = int(clamp(main_vel + 9 * richness, 42, 100))
                add_fifth = richness > 0.18

            elif sec_name == "S6" and s6_expr_ctx is not None:
                feats = s1_window_features(sec_df, sub_start_data, sub_start_data + sub_dur_data)
                drive_norm = norm_by_quantiles(
                    feats["drive"], s6_expr_ctx["drive_q50"], s6_expr_ctx["drive_q80"]
                )
                activity_norm = norm_by_quantiles(
                    feats["activity"], s6_expr_ctx["activity_q50"], s6_expr_ctx["activity_q80"]
                )
                richness = clamp(0.32 + 0.20 * activity_norm + 0.24 * drive_norm, 0.0, 1.0)

                if phrase_mode == "coda":
                    main_vel = int(clamp(main_vel + 4 * richness, 40, 88))
                    add_fifth = False
                elif phrase_mode == "s6_descent":
                    main_vel = int(clamp(main_vel + 5 * richness, 40, 90))
                    add_fifth = richness > 0.28
                else:
                    main_vel = int(clamp(main_vel + 6 * richness, 40, 92))
                    add_fifth = richness > 0.34

            add_note(
                piano_inst,
                pitch=ev["pitch"],
                start=humanize(piano_start, 0.003),
                end=humanize(piano_end, 0.003),
                vel=main_vel
            )

            fifth_pitch = ev["pitch"] + 7
            if add_fifth and fifth_pitch <= 72:
                add_note(
                    piano_inst,
                    pitch=fifth_pitch,
                    start=humanize(piano_start + 0.01, 0.002),
                    end=humanize(piano_end, 0.003),
                    vel=max(34, main_vel - 16)
                )

    return prev_pitch, routed_events, new_cello_events

# =========================
# データ読み込み
# =========================
random.seed(RANDOM_SEED)

SECTION_TIMING = read_section_timings_and_bpms(SECTION_XLSX)
SESSION_DF = load_session_timeseries(SESSION_CSV)
SECTION_STATS = build_section_feature_stats(SESSION_DF)
DRUM_STATS = build_drum_feature_stats(SESSION_DF)

S1_EXPR_CTX = build_s1_expression_context(S1_DETAIL_CSV)
S2_EXPR_CTX = build_s1_expression_context(S2_DETAIL_CSV)
S3_EXPR_CTX = build_s1_expression_context(S3_DETAIL_CSV)
S4_EXPR_CTX = build_s1_expression_context(S4_DETAIL_CSV)
S5_EXPR_CTX = build_s1_expression_context(S5_DETAIL_CSV)
S6_EXPR_CTX = build_s1_expression_context(S6_DETAIL_CSV)

avg_bpm = np.mean([SECTION_TIMING[s]["bpm"] for s in SECTION_ORDER])

print("=== Section BPMs from xlsx (variable bars, S5 cello tail v4 + R18 drums) ===")
for sec_name in SECTION_ORDER:
    info = SECTION_TIMING[sec_name]
    print(
        f"{sec_name}: {info['start']} - {info['end']}, "
        f"duration={info['duration_sec']:.1f}s, "
        f"bars={info['bars']}, BPM={info['bpm']:.3f}"
    )

# =========================
# MIDI作成
# =========================
pm = pretty_midi.PrettyMIDI(initial_tempo=float(avg_bpm))

piano = pretty_midi.Instrument(
    program=pretty_midi.instrument_name_to_program("Acoustic Grand Piano")
)
melody = pretty_midi.Instrument(
    program=pretty_midi.instrument_name_to_program("Cello")
)
drums = pretty_midi.Instrument(program=0, is_drum=True, name="R18 Drums")

t0 = 0.0
prev_melody_pitch = 62
prev_s6_rh_pitch = 67
s1_phrase_memory = {}

# =========================
# セクションごとに作成
# =========================
for sec_name in SECTION_ORDER:
    progression = SECTIONS[sec_name]
    expected_bars = SECTION_BARS[sec_name]
    if len(progression) != expected_bars:
        raise RuntimeError(f"{sec_name} must have {expected_bars} bars, got {len(progression)}")

    sec_info = SECTION_TIMING[sec_name]
    sec_df = SESSION_DF[SESSION_DF["session_id"] == sec_name].copy()
    if sec_df.empty:
        raise RuntimeError(f"No data for {sec_name} in session csv")

    sec_bpm = sec_info["bpm"]
    seconds_per_beat = sec_info["seconds_per_beat"]
    bar_duration = sec_info["bar_duration"]
    sec_duration_data = float(sec_info["duration_sec"])
    bars_this_section = sec_info["bars"]

    print(
        f"[INFO] composing {sec_name}: "
        f"BPM={sec_bpm:.3f}, "
        f"bars={bars_this_section}, "
        f"seconds_per_beat={seconds_per_beat:.4f}, "
        f"bar_duration={bar_duration:.4f}"
    )

    for bar_idx, bar_chord_text in enumerate(progression):
        bar_start_music = t0
        bar_start_data = (bar_idx / bars_this_section) * sec_duration_data

        sub_chords = split_bar_chords(bar_chord_text)
        sub_dur_music = bar_duration / len(sub_chords)
        sub_dur_data = (sec_duration_data / bars_this_section) / len(sub_chords)

        use_s1_recall = (sec_name == "S1" and 8 <= bar_idx <= 15)
        use_s5_recall = (sec_name == "S5" and 0 <= bar_idx <= 9)
        source_s1_bar = bar_idx - 8 if use_s1_recall else bar_idx

        phrase_mode = "normal"
        if sec_name == "S6":
            if 16 <= bar_idx <= 17:
                phrase_mode = "s6_bridge"
            elif 18 <= bar_idx <= 19:
                phrase_mode = "s6_descent"
            elif 20 <= bar_idx <= 23:
                phrase_mode = "coda"

        # ---- Piano Left Hand ----
        for sub_idx, chord_name in enumerate(sub_chords):
            sub_start_music = bar_start_music + sub_idx * sub_dur_music
            sub_start_data = bar_start_data + sub_idx * sub_dur_data

            richness = 0.0
            drive_norm = 0.0
            activity_norm = 0.0

            expr_ctx = None
            if sec_name == "S1" and S1_EXPR_CTX is not None:
                expr_ctx = S1_EXPR_CTX
            elif sec_name == "S2" and S2_EXPR_CTX is not None:
                expr_ctx = S2_EXPR_CTX
            elif sec_name == "S3" and S3_EXPR_CTX is not None:
                expr_ctx = S3_EXPR_CTX
            elif sec_name == "S4" and S4_EXPR_CTX is not None:
                expr_ctx = S4_EXPR_CTX
            elif sec_name == "S5" and S5_EXPR_CTX is not None:
                expr_ctx = S5_EXPR_CTX
            elif sec_name == "S6" and S6_EXPR_CTX is not None:
                expr_ctx = S6_EXPR_CTX

            if expr_ctx is not None:
                feats = s1_window_features(sec_df, sub_start_data, sub_start_data + sub_dur_data)
                drive_norm = norm_by_quantiles(
                    feats["drive"], expr_ctx["drive_q50"], expr_ctx["drive_q80"]
                )
                activity_norm = norm_by_quantiles(
                    feats["activity"], expr_ctx["activity_q50"], expr_ctx["activity_q80"]
                )

                if sec_name == "S1":
                    richness = 0.35 + 0.45 * activity_norm + 0.20 * drive_norm
                elif sec_name == "S2":
                    richness = 0.42 + 0.38 * activity_norm + 0.24 * drive_norm
                elif sec_name == "S3":
                    richness = 0.48 + 0.30 * activity_norm + 0.28 * drive_norm
                elif sec_name == "S4":
                    richness = 0.44 + 0.24 * activity_norm + 0.32 * drive_norm
                elif sec_name == "S5":
                    richness = 0.40 + 0.28 * activity_norm + 0.32 * drive_norm
                else:  # S6
                    richness = 0.28 + 0.18 * activity_norm + 0.22 * drive_norm
                    if phrase_mode == "coda":
                        richness *= 0.70

                richness = clamp(richness, 0.0, 1.0)

            if sec_name == "S1":
                voiced = voiced_with_optional_color(chord_name, richness, threshold=0.38)
            elif sec_name == "S2":
                voiced = voiced_with_optional_color(chord_name, richness, threshold=0.26)
            elif sec_name == "S3":
                voiced = voiced_with_optional_color(chord_name, richness, threshold=0.12)
            elif sec_name == "S4":
                voiced = voiced_with_optional_color(chord_name, richness, threshold=0.18)
            elif sec_name == "S5":
                voiced = voiced_with_optional_color(chord_name, richness, threshold=0.20)
            elif sec_name == "S6":
                voiced = voiced_with_optional_color(chord_name, richness, threshold=0.36 if phrase_mode != "coda" else 0.55)
            else:
                voiced = voiced_with_optional_color(chord_name, 0.0, threshold=1.0)

            base_len = (0.98 if phrase_mode == "coda" else 0.96)
            lh_len = base_len
            lh_vel_boost = 0
            lh_push = 0.0

            if sec_name == "S1":
                lh_len = clamp(base_len - 0.03 * activity_norm + 0.015 * drive_norm, 0.90, 0.99)
                lh_vel_boost = int(round(3 * richness))
                lh_push = (-0.006 * activity_norm + 0.004 * drive_norm)
            elif sec_name == "S2":
                lh_len = clamp(base_len - 0.02 * activity_norm + 0.020 * drive_norm, 0.91, 1.00)
                lh_vel_boost = int(round(4 * richness))
                lh_push = (-0.004 * activity_norm + 0.006 * drive_norm)
            elif sec_name == "S3":
                lh_len = clamp(base_len - 0.01 * activity_norm + 0.025 * drive_norm, 0.93, 1.02)
                lh_vel_boost = int(round(5 * richness))
                lh_push = (-0.002 * activity_norm + 0.007 * drive_norm)
            elif sec_name == "S4":
                lh_len = clamp(base_len - 0.02 * activity_norm + 0.020 * drive_norm, 0.90, 0.99)
                lh_vel_boost = int(round(4 * richness))
                lh_push = (-0.003 * activity_norm + 0.005 * drive_norm)
            elif sec_name == "S5":
                lh_len = clamp(base_len - 0.015 * activity_norm + 0.022 * drive_norm, 0.91, 1.00)
                lh_vel_boost = int(round(4 * richness))
                lh_push = (-0.002 * activity_norm + 0.006 * drive_norm)
            elif sec_name == "S6":
                if phrase_mode == "coda":
                    lh_len = clamp(base_len - 0.01 * activity_norm + 0.010 * drive_norm, 0.94, 1.00)
                    lh_vel_boost = int(round(2 * richness))
                    lh_push = (-0.001 * activity_norm + 0.002 * drive_norm)
                elif phrase_mode == "s6_descent":
                    lh_len = clamp(base_len - 0.012 * activity_norm + 0.014 * drive_norm, 0.93, 1.00)
                    lh_vel_boost = int(round(3 * richness))
                    lh_push = (-0.001 * activity_norm + 0.003 * drive_norm)
                else:
                    lh_len = clamp(base_len - 0.015 * activity_norm + 0.018 * drive_norm, 0.92, 1.00)
                    lh_vel_boost = int(round(3 * richness))
                    lh_push = (-0.002 * activity_norm + 0.004 * drive_norm)

            sub_end_music = sub_start_music + sub_dur_music * lh_len

            for k, pitch in enumerate(voiced):
                vel = (54 if phrase_mode == "coda" else 58) - k * 4 + lh_vel_boost
                add_note(
                    piano,
                    pitch=pitch,
                    start=humanize(sub_start_music + lh_push * seconds_per_beat + 0.003 * k, 0.0015),
                    end=humanize(sub_end_music, 0.0015),
                    vel=vel
                )

            if voiced:
                bass_root = min(voiced)
                bass_len = (0.92 if sec_name == "S6" else 0.88)
                if sec_name == "S1":
                    bass_len = clamp(bass_len - 0.03 * activity_norm + 0.01 * drive_norm, 0.82, 0.90)
                elif sec_name == "S2":
                    bass_len = clamp(bass_len - 0.02 * activity_norm + 0.015 * drive_norm, 0.84, 0.92)
                elif sec_name == "S3":
                    bass_len = clamp(bass_len - 0.01 * activity_norm + 0.020 * drive_norm, 0.86, 0.96)
                elif sec_name == "S4":
                    bass_len = clamp(bass_len - 0.02 * activity_norm + 0.015 * drive_norm, 0.84, 0.92)
                elif sec_name == "S5":
                    bass_len = clamp(bass_len - 0.015 * activity_norm + 0.018 * drive_norm, 0.85, 0.93)
                elif sec_name == "S6":
                    if phrase_mode == "coda":
                        bass_len = clamp(bass_len - 0.005 * activity_norm + 0.008 * drive_norm, 0.86, 0.92)
                    else:
                        bass_len = clamp(bass_len - 0.010 * activity_norm + 0.012 * drive_norm, 0.85, 0.92)

                bass_vel = (48 if sec_name == "S6" else 50) + int(round(2 * richness))

                add_note(
                    piano,
                    pitch=max(28, bass_root - 12),
                    start=humanize(sub_start_music + lh_push * seconds_per_beat, 0.0015),
                    end=humanize(sub_start_music + sub_dur_music * bass_len, 0.0015),
                    vel=bass_vel
                )

        # ---- Drums (R18 sway) ----
        for sub_idx, chord_name in enumerate(sub_chords):
            sub_start_music = bar_start_music + sub_idx * sub_dur_music
            sub_start_data = bar_start_data + sub_idx * sub_dur_data

            add_r18_drum_layer_for_subchord(
                drum_inst=drums,
                sec_df=sec_df,
                sec_name=sec_name,
                sub_start_music=sub_start_music,
                sub_dur_music=sub_dur_music,
                sub_start_data=sub_start_data,
                sub_dur_data=sub_dur_data,
                seconds_per_beat=seconds_per_beat,
                drum_stats=DRUM_STATS,
                phrase_mode=phrase_mode,
            )

        # ---- 主旋律 ----
        if (use_s1_recall or use_s5_recall) and source_s1_bar in s1_phrase_memory:
            recalled_events = transform_repeated_phrase_events(
                s1_phrase_memory[source_s1_bar],
                chord_name=sub_chords[0]
            )

            if use_s5_recall:
                recalled_events = extend_s5_tail_on_cello(
                    recalled_events=recalled_events,
                    bar_duration=bar_duration,
                    seconds_per_beat=seconds_per_beat,
                    bar_idx=bar_idx,
                )
                recalled_events = reinforce_s5_bars_6_7_on_cello(
                    recalled_events=recalled_events,
                    chord_name=sub_chords[0],
                    bar_idx=bar_idx,
                    seconds_per_beat=seconds_per_beat,
                )

            for ev in recalled_events:
                new_start = bar_start_music + ev["start"]
                new_end = bar_start_music + ev["end"]

                if ev["source"] == "cello":
                    out_vel = ev["vel"]

                    if use_s5_recall and S5_EXPR_CTX is not None:
                        feats = s1_window_features(
                            sec_df,
                            bar_start_data,
                            bar_start_data + (sec_duration_data / bars_this_section)
                        )
                        drive_norm = norm_by_quantiles(
                            feats["drive"], S5_EXPR_CTX["drive_q50"], S5_EXPR_CTX["drive_q80"]
                        )
                        activity_norm = norm_by_quantiles(
                            feats["activity"], S5_EXPR_CTX["activity_q50"], S5_EXPR_CTX["activity_q80"]
                        )
                        richness = clamp(0.40 + 0.32 * activity_norm + 0.30 * drive_norm, 0.0, 1.0)
                        out_vel = int(clamp(out_vel + 6 * richness + 4 * drive_norm, 52, 112))

                    add_note(
                        melody,
                        pitch=ev["pitch"],
                        start=humanize(new_start, 0.004),
                        end=humanize(new_end, 0.004),
                        vel=out_vel
                    )
                else:
                    out_vel = ev["vel"]

                    if use_s5_recall and S5_EXPR_CTX is not None:
                        feats = s1_window_features(
                            sec_df,
                            bar_start_data,
                            bar_start_data + (sec_duration_data / bars_this_section)
                        )
                        drive_norm = norm_by_quantiles(
                            feats["drive"], S5_EXPR_CTX["drive_q50"], S5_EXPR_CTX["drive_q80"]
                        )
                        activity_norm = norm_by_quantiles(
                            feats["activity"], S5_EXPR_CTX["activity_q50"], S5_EXPR_CTX["activity_q80"]
                        )
                        richness = clamp(0.40 + 0.32 * activity_norm + 0.30 * drive_norm, 0.0, 1.0)
                        out_vel = int(clamp(out_vel + 5 * richness, 38, 96))

                    add_note(
                        piano,
                        pitch=ev["pitch"],
                        start=humanize(new_start, 0.003),
                        end=humanize(new_end, 0.003),
                        vel=out_vel
                    )
                    fifth_pitch = ev["pitch"] + 7
                    if fifth_pitch <= 72:
                        add_note(
                            piano,
                            pitch=fifth_pitch,
                            start=humanize(new_start + 0.01, 0.002),
                            end=humanize(new_end, 0.003),
                            vel=max(34, ev["vel"] - 16)
                        )

        else:
            bar_event_memory = []
            s4_new_cello_events = []

            for sub_idx, chord_name in enumerate(sub_chords):
                sub_start_music = bar_start_music + sub_idx * sub_dur_music
                sub_start_data = bar_start_data + sub_idx * sub_dur_data

                before_cello_n = len(melody.notes)
                before_piano_n = len(piano.notes)

                prev_melody_pitch, routed_events, new_cello_events = add_data_driven_melody_for_subchord(
                    melody_inst=melody,
                    piano_inst=piano,
                    sec_df=sec_df,
                    sec_name=sec_name,
                    chord_name=chord_name,
                    sub_start_music=sub_start_music,
                    sub_dur_music=sub_dur_music,
                    sub_start_data=sub_start_data,
                    sub_dur_data=sub_dur_data,
                    seconds_per_beat=seconds_per_beat,
                    prev_pitch=prev_melody_pitch,
                    stats=SECTION_STATS,
                    phrase_mode=phrase_mode,
                    s1_expr_ctx=S1_EXPR_CTX,
                    s2_expr_ctx=S2_EXPR_CTX,
                    s3_expr_ctx=S3_EXPR_CTX,
                    s4_expr_ctx=S4_EXPR_CTX,
                    s5_expr_ctx=S5_EXPR_CTX,
                    s6_expr_ctx=S6_EXPR_CTX,
                )

                new_cello_notes = melody.notes[before_cello_n:]
                new_piano_notes = piano.notes[before_piano_n:]

                if sec_name == "S1" and 0 <= bar_idx <= 7:
                    for n in new_cello_notes:
                        bar_event_memory.append({
                            "pitch": n.pitch,
                            "start": n.start - bar_start_music,
                            "end": n.end - bar_start_music,
                            "vel": n.velocity,
                            "source": "cello",
                        })
                    for n in new_piano_notes:
                        if 48 <= n.pitch <= 72:
                            bar_event_memory.append({
                                "pitch": n.pitch,
                                "start": n.start - bar_start_music,
                                "end": n.end - bar_start_music,
                                "vel": n.velocity,
                                "source": "piano",
                            })

                if sec_name == "S4":
                    for n in new_cello_notes:
                        s4_new_cello_events.append({
                            "pitch": n.pitch,
                            "start": n.start - bar_start_music,
                            "end": n.end - bar_start_music,
                            "vel": n.velocity,
                        })

            if sec_name == "S1" and 0 <= bar_idx <= 7:
                s1_phrase_memory[bar_idx] = sorted(bar_event_memory, key=lambda e: e["start"])

            if sec_name == "S4":
                main_chord_for_response = sub_chords[0]
                add_s4_piano_response(
                    piano_inst=piano,
                    chord_name=main_chord_for_response,
                    cello_events=sorted(s4_new_cello_events, key=lambda e: e["start"]),
                    bar_start_music=bar_start_music,
                    seconds_per_beat=seconds_per_beat,
                    sec_df=sec_df,
                    bar_start_data=bar_start_data,
                    bar_duration_data=sec_duration_data / bars_this_section,
                    s4_expr_ctx=S4_EXPR_CTX,
                )

            if sec_name == "S6":
                main_chord_for_response = sub_chords[0]
                prev_s6_rh_pitch = add_s6_piano_response_like_s1(
                    piano_inst=piano,
                    chord_name=main_chord_for_response,
                    bar_idx=bar_idx,
                    bar_start_music=bar_start_music,
                    seconds_per_beat=seconds_per_beat,
                    sub_dur_music=bar_duration,
                    prev_rh_pitch_holder=prev_s6_rh_pitch,
                    sec_df=sec_df,
                    bar_start_data=bar_start_data,
                    bar_duration_data=sec_duration_data / bars_this_section,
                    s6_expr_ctx=S6_EXPR_CTX,
                    phrase_mode=phrase_mode,
                )

        t0 += bar_duration

pm.instruments.append(piano)
pm.instruments.append(melody)
pm.instruments.append(drums)
pm.write(str(MIDI_OUT))
print(f"[OK] MIDI created: {MIDI_OUT}")

# =========================
# 存在チェック
# =========================
if not FLUIDSYNTH.exists():
    raise FileNotFoundError(f"fluidsynth.exe not found: {FLUIDSYNTH}")
if not SOUNDFONT.exists():
    raise FileNotFoundError(f"SoundFont not found: {SOUNDFONT}")
if not MIDI_OUT.exists():
    raise FileNotFoundError(f"MIDI not found: {MIDI_OUT}")

# =========================
# MIDI → WAV
# =========================
cmd = [
    str(FLUIDSYNTH),
    "-ni",
    "-F", str(WAV_OUT),
    "-T", "wav",
    "-r", "44100",
    str(SOUNDFONT),
    str(MIDI_OUT),
]

print("[INFO] Running:", " ".join(cmd))
p = subprocess.run(cmd, capture_output=True, text=True)

if p.stdout.strip():
    print(p.stdout)
if p.stderr.strip():
    print(p.stderr)

if WAV_OUT.exists() and WAV_OUT.stat().st_size > 1000:
    print(f"[OK] WAV created: {WAV_OUT}")
else:
    raise RuntimeError("WAV was not created. See FluidSynth output above.")