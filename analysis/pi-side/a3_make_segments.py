#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
701 Lab A3: Segments generator (run_dir -> derived/segments_*.csv)

What this does (Pi-side, deterministic):
- Auto-detect latest run_* under runs_root (default: /media/seven_zero_one/MF-SU2C/701lab_data/runs)
- Reads unified.csv (t_mono timeline facts)
- Reads status.csv (event/exception/restart scan; robust CSV parsing)
- Optionally reads derived/qc_report.json (quality hints; overall + audio status)
- Optionally reads raw/audio.wav header (duration sanity)
- Generates segments (t_mono start/end + reason) as CSV under run_dir/derived/:

  derived/segments_run.csv    : overall MEASURING interval (t_mono_min..t_mono_max)
  derived/segments_gps.csv    : contiguous intervals where gps.fix == 1
  derived/segments_audio.csv  : audio usable interval (default = segments_run) if audio_basic OK/WARN and duration sane
  derived/segments_polar.csv  : connected intervals inferred from status.csv polar worker_start/worker_stop; split by restart
  derived/segments_imu.csv    : IMU usable interval (default = segments_run); can be extended to split on timeout/drop later

Notes:
- No interpolation, no sync estimation.
- Uses only stdlib.

Usage:
  python3 a3_make_segments.py
  python3 a3_make_segments.py --runs-root /media/seven_zero_one/MF-SU2C/701lab_data/runs
  python3 a3_make_segments.py --run-dir /path/to/run_xxx
  python3 a3_make_segments.py --print

Outputs:
  <run_dir>/derived/segments_*.csv
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


DEFAULT_RUNS_ROOT = "/media/seven_zero_one/MF-SU2C/701lab_data/runs"


def iso_now() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def safe_float(x: str) -> Optional[float]:
    try:
        v = float(x)
        return v if v == v else None
    except Exception:
        return None


def safe_int(x: str) -> Optional[int]:
    try:
        return int(float(x))
    except Exception:
        return None


def read_json(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    if not path.exists():
        return None, f"missing: {path}"
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, f"failed to read json: {path} err={e}"


def find_latest_run(runs_root: Path) -> Path:
    runs = [p for p in runs_root.glob("run_*") if p.is_dir()]
    if not runs:
        raise FileNotFoundError(f"No run_* directories found under {runs_root}")
    runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return runs[0]


@dataclass
class Segment:
    t_start: float
    t_end: float
    reason: str

    def clamp(self, lo: float, hi: float) -> "Segment":
        return Segment(max(self.t_start, lo), min(self.t_end, hi), self.reason)

    def is_valid(self, min_len: float = 1e-6) -> bool:
        return (self.t_end - self.t_start) > min_len


def write_segments_csv(path: Path, segments: List[Segment]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_start", "t_end", "reason"])
        for s in segments:
            w.writerow([f"{s.t_start:.6f}", f"{s.t_end:.6f}", s.reason])


# -------------------------
# Unified parsing (only what we need)
# -------------------------

def scan_unified_bounds(unified_path: Path) -> Tuple[Optional[Tuple[float, float]], Optional[str]]:
    """
    Returns (t_min, t_max) for all rows with parsable t_mono.
    """
    if not unified_path.exists():
        return None, "missing unified.csv"
    t_min = None
    t_max = None
    try:
        with unified_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None or "t_mono" not in reader.fieldnames:
                return None, f"bad unified header: {reader.fieldnames}"
            for row in reader:
                t = safe_float(row.get("t_mono", ""))
                if t is None:
                    continue
                if t_min is None or t < t_min:
                    t_min = t
                if t_max is None or t > t_max:
                    t_max = t
        if t_min is None or t_max is None:
            return None, "no t_mono values found in unified.csv"
        return (t_min, t_max), None
    except Exception as e:
        return None, f"failed to scan unified bounds: {e}"


def segments_gps_fix1(unified_path: Path) -> Tuple[List[Segment], Dict[str, object]]:
    """
    Build contiguous segments where source=gps and name=fix and value==1.
    We assume unified is time-sorted (QC already checks monotonic).
    """
    segs: List[Segment] = []
    stats = {
        "fix_rows": 0,
        "fix1_rows": 0,
        "segments": 0,
    }

    in_seg = False
    t_start = None
    last_t = None

    with unified_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("source") != "gps" or row.get("name") != "fix":
                continue
            stats["fix_rows"] += 1

            t = safe_float(row.get("t_mono", ""))
            v = safe_int(row.get("value", ""))
            if t is None or v is None:
                continue

            if v == 1:
                stats["fix1_rows"] += 1
                if not in_seg:
                    in_seg = True
                    t_start = t
                last_t = t
            else:
                if in_seg and t_start is not None and last_t is not None:
                    segs.append(Segment(t_start, last_t, "fix_1"))
                    in_seg = False
                    t_start = None
                    last_t = None

    if in_seg and t_start is not None and last_t is not None:
        segs.append(Segment(t_start, last_t, "fix_1"))

    stats["segments"] = len(segs)
    return segs, stats

def segments_polar_from_unified(
    unified_path: Path,
    gap_sec: Optional[float] = None,
) -> Tuple[List[Segment], Dict[str, object]]:
    """
    Build polar segments from unified.csv (authoritative).

    Default behavior (gap_sec is None):
      - Return a single segment [t_min, t_max] for source=polar.
      - This matches the pipeline goal: "sensor effective interval".

    Optional behavior (gap_sec is not None):
      - Split into multiple segments if gaps in t_mono > gap_sec.
      - Use only if you explicitly want to treat long dropouts as inactive.
    """
    stats: Dict[str, object] = {
        "polar_rows": 0,
        "t_min": None,
        "t_max": None,
        "gap_sec": gap_sec,
        "gap_splits": 0,
        "segments": 0,
    }

    # First pass: just min/max
    t_min: Optional[float] = None
    t_max: Optional[float] = None

    times: List[float] = []  # only used when gap_sec is enabled
    with unified_path.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            if row.get("source") != "polar":
                continue
            t = safe_float(row.get("t_mono", ""))
            if t is None:
                continue
            stats["polar_rows"] += 1
            if t_min is None or t < t_min:
                t_min = t
            if t_max is None or t > t_max:
                t_max = t
            if gap_sec is not None:
                times.append(t)

    stats["t_min"] = t_min
    stats["t_max"] = t_max

    if t_min is None or t_max is None or t_max <= t_min:
        stats["segments"] = 0
        return [], stats

    # Default: single effective interval
    if gap_sec is None:
        segs = [Segment(t_min, t_max, "polar_present")]
        stats["segments"] = 1
        return segs, stats

    # Optional: gap splitting
    times.sort()
    segs: List[Segment] = []
    cur_start = times[0]
    cur_last = times[0]

    for t in times[1:]:
        if (t - cur_last) > gap_sec:
            segs.append(Segment(cur_start, cur_last, "polar_present"))
            stats["gap_splits"] += 1
            cur_start = t
        cur_last = t

    segs.append(Segment(cur_start, cur_last, "polar_present"))
    stats["segments"] = len(segs)
    return segs, stats




# -------------------------
# Status parsing (robust)
# -------------------------

def parse_status_events(status_path: Path) -> Tuple[List[dict], Optional[str]]:
    """
    Parse status.csv as DictReader if possible.
    Expected-ish columns:
      seq,t_mono,t_wall,level,event,message
    But it's OK if names differ; we try to read common ones.
    """
    if not status_path.exists():
        return [], "missing status.csv"

    events: List[dict] = []
    try:
        with status_path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            # If header not parseable, fallback to line scan
            if reader.fieldnames is None:
                return [], "status.csv has no header"
            # common keys
            for row in reader:
                # keep raw row plus best-effort extracted fields
                t = safe_float(row.get("t_mono", "") or row.get("tMono", "") or row.get("mono", ""))
                event = (row.get("event") or row.get("type") or row.get("name") or "").strip()
                level = (row.get("level") or row.get("lvl") or "").strip()
                msg = (row.get("message") or row.get("msg") or row.get("detail") or "").strip()
                # Some logs put everything into one column; if so, keep row as is.
                events.append({
                    "t_mono": t,
                    "event": event,
                    "level": level,
                    "message": msg,
                    "row": row,
                })
        return events, None
    except Exception as e:
        return [], f"failed to parse status.csv: {e}"


def segments_polar_from_status(events: List[dict]) -> Tuple[List[Segment], Dict[str, object]]:
    """
    Infer Polar connected segments.
    We use events that contain:
      - worker_start with name=polar
      - worker_stop  with name=polar
      - polar_restart
    We parse 'message' field patterns like:
      "name=polar ..."
      "polar_restart,reason=idle_timeout count=1"
    This is robust to your current status format.

    Output segments:
      reason: "polar_connected"
    """
    segs: List[Segment] = []
    stats = {
        "worker_start": 0,
        "worker_stop": 0,
        "restart": 0,
        "open_segments": 0,
    }

    # helpers to detect polar
    def is_polar_line(ev: dict) -> bool:
        event = (ev.get("event") or "").lower()
        msg = (ev.get("message") or "").lower()
        # status samples show "worker_start" with "name=polar" in message
        if "polar" in event:
            return True
        if "name=polar" in msg:
            return True
        if "polar_restart" in event or "polar_restart" in msg:
            return True
        if "worker_start" in event and "polar" in msg:
            return True
        if "worker_stop" in event and "polar" in msg:
            return True
        return False

    def is_worker_start_polar(ev: dict) -> bool:
        event = (ev.get("event") or "").lower()
        msg = (ev.get("message") or "").lower()
        return ("worker_start" in event) and ("name=polar" in msg or " polar" in msg)

    def is_worker_stop_polar(ev: dict) -> bool:
        event = (ev.get("event") or "").lower()
        msg = (ev.get("message") or "").lower()
        return ("worker_stop" in event) and ("name=polar" in msg or " polar" in msg)

    def is_restart(ev: dict) -> bool:
        event = (ev.get("event") or "").lower()
        msg = (ev.get("message") or "").lower()
        return ("polar_restart" in event) or ("polar_restart" in msg)

    in_seg = False
    t_start = None
    last_t = None

    # traverse in time order
    for ev in events:
        t = ev.get("t_mono")
        if t is None:
            continue
        if not is_polar_line(ev):
            continue

        if is_worker_start_polar(ev):
            stats["worker_start"] += 1
            # close any open segment (defensive)
            if in_seg and t_start is not None and last_t is not None:
                segs.append(Segment(t_start, last_t, "polar_connected"))
            in_seg = True
            t_start = t
            last_t = t
            continue

        if is_restart(ev):
            stats["restart"] += 1
            # restart implies a disconnection boundary; close current segment at this time
            if in_seg and t_start is not None and last_t is not None:
                segs.append(Segment(t_start, t, "polar_connected"))
            # reopen immediately (best-effort) because restart usually re-connects right away
            in_seg = True
            t_start = t
            last_t = t
            continue

        if is_worker_stop_polar(ev):
            stats["worker_stop"] += 1
            if in_seg and t_start is not None:
                segs.append(Segment(t_start, t, "polar_connected"))
            in_seg = False
            t_start = None
            last_t = None
            continue

        # Other polar-related lines: just update last time to allow a non-empty segment
        if in_seg:
            last_t = t

    # close tail
    if in_seg and t_start is not None and last_t is not None and last_t > t_start:
        segs.append(Segment(t_start, last_t, "polar_connected"))

    stats["open_segments"] = len(segs)
    return segs, stats


def extract_polar_restart_times_from_status(events: List[dict]) -> List[float]:
    """
    Extract restart boundary times from status events.
    We look for lines whose event/message indicates polar_restart.
    """
    ts: List[float] = []
    for ev in events:
        t = ev.get("t_mono")
        if t is None:
            continue
        event = (ev.get("event") or "").lower()
        msg = (ev.get("message") or "").lower()
        if ("polar_restart" in event) or ("polar_restart" in msg):
            ts.append(float(t))
    ts.sort()
    return ts

def split_segments_by_times(segs: List[Segment], split_times: List[float], reason_suffix: str) -> List[Segment]:
    """
    Split each segment by boundary times in split_times.
    Keeps only valid (positive-length) segments.
    """
    if not segs or not split_times:
        return segs

    out: List[Segment] = []
    for s in segs:
        cuts = [t for t in split_times if s.t_start < t < s.t_end]
        if not cuts:
            out.append(s)
            continue
        pts = [s.t_start] + cuts + [s.t_end]
        for a, b in zip(pts[:-1], pts[1:]):
            seg = Segment(a, b, s.reason + reason_suffix)
            if seg.is_valid():
                out.append(seg)
    return out

# -------------------------
# Audio segment logic
# -------------------------

def wav_duration_sec(wav_path: Path) -> Tuple[Optional[float], Optional[str]]:
    if not wav_path.exists():
        return None, "missing audio.wav"
    try:
        with wave.open(str(wav_path), "rb") as w:
            sr = w.getframerate()
            nframes = w.getnframes()
            if sr <= 0:
                return None, "invalid sample rate"
            return nframes / float(sr), None
    except Exception as e:
        return None, f"failed to read wav duration: {e}"


def decide_audio_segment(
    run_seg: Segment,
    qc: Optional[dict],
    wav_path: Path,
    allow_warn: bool = True,
) -> Tuple[List[Segment], Dict[str, object]]:
    """
    If QC says audio is OK, accept run segment (clamped by wav duration if needed).
    If QC says audio is WARN, accept if allow_warn=True.
    If QC says audio is FAIL or missing, return empty.
    Also checks duration mismatch: if absolute mismatch > max(3s, 10% run) => WARN and clamp to min(run,wav)
    """
    stats: Dict[str, object] = {}
    # default qc decision
    qc_level = None
    qc_msg = None
    if isinstance(qc, dict):
        c = (qc.get("checks") or {}).get("audio_basic")
        if isinstance(c, dict):
            qc_level = c.get("level")
            qc_msg = c.get("message")

    stats["qc_level"] = qc_level
    stats["qc_message"] = qc_msg

    if qc_level == "FAIL":
        return [], {**stats, "decision": "reject_audio_qc_fail"}

    if qc_level == "WARN" and not allow_warn:
        return [], {**stats, "decision": "reject_audio_qc_warn"}

    # If no qc, be conservative but still allow if wav exists
    dur_wav, err = wav_duration_sec(wav_path)
    stats["wav_duration_sec"] = dur_wav
    stats["wav_err"] = err

    if dur_wav is None:
        return [], {**stats, "decision": "reject_no_wav"}

    # Compare run duration vs wav duration
    run_dur = run_seg.t_end - run_seg.t_start
    diff = abs(dur_wav - run_dur)
    stats["run_duration_sec"] = run_dur
    stats["duration_diff_sec"] = diff

    # clamp segment to wav duration assuming audio starts at run start (current logger behavior)
    # (If later you log an explicit audio_start t_mono event, we will use that.)
    t_end_audio = run_seg.t_start + min(run_dur, dur_wav)
    seg = Segment(run_seg.t_start, t_end_audio, "recording")

    # decide accept
    # If QC is missing, we accept but mark reason; if QC OK/WARN, accept.
    decision = "accept"
    if diff > max(3.0, 0.1 * max(run_dur, 1e-6)):
        # still accept but it's a red flag; keep segment clamped
        decision = "accept_with_mismatch_warning"

    stats["decision"] = decision
    return [seg], stats


# -------------------------
# Main
# -------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-root", default=DEFAULT_RUNS_ROOT, help="runs root containing run_*")
    ap.add_argument("--run-dir", default=None, help="explicit run_dir (overrides latest autodetect)")
    ap.add_argument("--print", action="store_true", help="print generated segment file paths")
    ap.add_argument("--audio-allow-warn", action="store_true", help="accept audio segment even if QC audio_basic is WARN")
    args = ap.parse_args()

    runs_root = Path(args.runs_root)
    run_dir = Path(args.run_dir) if args.run_dir else find_latest_run(runs_root)

    if not run_dir.exists() or not run_dir.is_dir():
        print(f"ERROR: run_dir not found: {run_dir}", file=sys.stderr)
        return 2

    unified_path = run_dir / "unified.csv"
    status_path = run_dir / "status.csv"
    qc_path = run_dir / "derived" / "qc_report.json"
    wav_path = run_dir / "raw" / "audio.wav"

    derived_dir = run_dir / "derived"
    ensure_dir(derived_dir)

    # 1) run bounds from unified
    bounds, berr = scan_unified_bounds(unified_path)
    if bounds is None:
        print(f"ERROR: cannot determine run bounds from unified.csv: {berr}", file=sys.stderr)
        return 2
    t_min, t_max = bounds
    run_seg = Segment(t_min, t_max, "measuring")

    # 2) qc optional
    qc, _ = read_json(qc_path)

    # 3) gps segments
    gps_segs, gps_stats = segments_gps_fix1(unified_path)
    # clamp to run bounds
    gps_segs = [s.clamp(t_min, t_max) for s in gps_segs if s.clamp(t_min, t_max).is_valid()]

    # 4) polar segments (AUTHORITATIVE: from unified; status used only for restart boundaries)
    # status events optional (for restart split)
    events, _ = parse_status_events(status_path)
    events.sort(key=lambda e: (e.get("t_mono") is None, e.get("t_mono") or 0.0))
    restart_times = extract_polar_restart_times_from_status(events)

    polar_segs_u, polar_stats_u = segments_polar_from_unified(unified_path, gap_sec=None)


    # split by restart boundaries if any
    polar_segs = split_segments_by_times(polar_segs_u, restart_times, reason_suffix="")

    # clamp to run bounds
    polar_segs = [s.clamp(t_min, t_max) for s in polar_segs if s.clamp(t_min, t_max).is_valid()]

    # Keep status-derived stats too (debug only)
    _, polar_stats_s = segments_polar_from_status(events)
    polar_stats = {
        "unified": polar_stats_u,
        "status": polar_stats_s,
        "restart_times": restart_times,
    }


    # 5) audio segment
    audio_allow_warn = bool(args.audio_allow_warn)
    audio_segs, audio_stats = decide_audio_segment(run_seg, qc, wav_path, allow_warn=audio_allow_warn)
    audio_segs = [s.clamp(t_min, t_max) for s in audio_segs if s.clamp(t_min, t_max).is_valid()]

    # 6) imu segment (simple for now: full run)
    imu_segs = [Segment(t_min, t_max, "imu_present")]  # can refine later with health facts

    # 7) write outputs
    out_run = derived_dir / "segments_run.csv"
    out_gps = derived_dir / "segments_gps.csv"
    out_audio = derived_dir / "segments_audio.csv"
    out_polar = derived_dir / "segments_polar.csv"
    out_imu = derived_dir / "segments_imu.csv"
    out_meta = derived_dir / "segments_meta.json"

    write_segments_csv(out_run, [run_seg])
    write_segments_csv(out_gps, gps_segs)
    write_segments_csv(out_audio, audio_segs)
    write_segments_csv(out_polar, polar_segs)
    write_segments_csv(out_imu, imu_segs)

    # helpful meta for debugging/traceability
    meta = {
        "created_at": iso_now(),
        "run_id": run_dir.name,
        "bounds": {"t_min": t_min, "t_max": t_max, "duration_sec": t_max - t_min},
        "gps": gps_stats,
        "polar": polar_stats,
        "audio": audio_stats,
        "notes": [
            "segments_* are expressed in t_mono seconds.",
            "segments_run is derived from unified.csv t_mono min/max.",
            "segments_audio assumes audio starts at run start; later, replace with explicit audio_start event if logged.",
        ],
    }
    with out_meta.open("w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    if args.print:
        print(out_run)
        print(out_gps)
        print(out_audio)
        print(out_polar)
        print(out_imu)
        print(out_meta)
    else:
        print(f"{run_dir.name}: wrote segments_* under {derived_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
