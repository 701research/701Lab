#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
701 Lab A4: Events generator (run_dir -> derived/events.csv)

Goal:
- Normalize events (START/STOP/RESTART/EXCEPTION/QUALITY) into a single table for downstream use.
- Deterministic & Pi-friendly (stdlib only).
- Auto-detect latest run under runs_root by default.

Inputs:
- unified.csv (for run bounds, state/ui events if present)
- status.csv (for worker_start/worker_stop/restart/exception; robust parsing)
- derived/qc_report.json (optional; overall + key warnings)
- derived/segments_*.csv (optional; for convenience annotations)

Outputs:
- derived/events.csv
- derived/events_meta.json

Event schema (events.csv):
- seq        : monotonically increasing integer within this file
- t_mono     : float seconds (authoritative time base)
- t_wall     : ISO8601 string if available, else empty
- level      : INFO/WARN/ERROR
- event      : normalized event name (RUN_START, RUN_STOP, POLAR_RESTART, EXCEPTION, ...)
- source     : unified/status/qc/segments
- detail     : compact key=value;... string (machine & human readable)

Usage:
  python3 a4_make_events.py
  python3 a4_make_events.py --runs-root /media/seven_zero_one/MF-SU2C/701lab_data/runs
  python3 a4_make_events.py --run-dir /path/to/run_xxx
  python3 a4_make_events.py --print
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


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
class Event:
    t_mono: float
    t_wall: str
    level: str
    event: str
    source: str
    detail: str


def scan_unified_bounds(unified_path: Path) -> Tuple[Optional[Tuple[float, float]], Optional[str]]:
    if not unified_path.exists():
        return None, "missing unified.csv"
    t_min = None
    t_max = None
    try:
        with unified_path.open("r", encoding="utf-8", newline="") as f:
            r = csv.DictReader(f)
            if r.fieldnames is None or "t_mono" not in r.fieldnames:
                return None, f"bad unified header: {r.fieldnames}"
            for row in r:
                t = safe_float(row.get("t_mono", ""))
                if t is None:
                    continue
                if t_min is None or t < t_min:
                    t_min = t
                if t_max is None or t > t_max:
                    t_max = t
        if t_min is None or t_max is None:
            return None, "no t_mono values in unified.csv"
        return (t_min, t_max), None
    except Exception as e:
        return None, f"failed to scan unified bounds: {e}"


def first_last_wall_times(unified_path: Path) -> Tuple[str, str]:
    """
    Best-effort: take first/last non-empty t_wall in unified.
    """
    t0 = ""
    t1 = ""
    try:
        with unified_path.open("r", encoding="utf-8", newline="") as f:
            r = csv.DictReader(f)
            for row in r:
                tw = (row.get("t_wall") or "").strip()
                if tw and not t0:
                    t0 = tw
                if tw:
                    t1 = tw
    except Exception:
        pass
    return t0, t1


def parse_status_rows(status_path: Path) -> List[dict]:
    """
    Robust-ish CSV parsing of status.csv.
    Keeps original row dict.
    """
    rows: List[dict] = []
    if not status_path.exists():
        return rows
    with status_path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        r = csv.DictReader(f)
        if r.fieldnames is None:
            return rows
        for row in r:
            rows.append(row)
    return rows


def status_extract_fields(row: dict) -> Tuple[Optional[float], str, str, str]:
    """
    Extract (t_mono, level, event, message) from a status row with unknown headers.
    """
    # common columns
    t = safe_float(row.get("t_mono", "") or row.get("tMono", "") or row.get("mono", "") or "")
    lvl = (row.get("level") or row.get("lvl") or "").strip()
    ev = (row.get("event") or row.get("type") or row.get("name") or "").strip()
    msg = (row.get("message") or row.get("msg") or row.get("detail") or "").strip()

    # Sometimes status is like: seq,t_mono,t_wall,LEVEL,EVENT,MESSAGE (no headers match)
    # If the parser used those as headers, we're fine. If not, we still just best-effort.

    return t, lvl, ev, msg


def kv_detail(**kwargs) -> str:
    parts = []
    for k, v in kwargs.items():
        if v is None:
            continue
        s = str(v)
        if s == "":
            continue
        parts.append(f"{k}={s}")
    return ";".join(parts)


def normalize_level(x: str) -> str:
    x = (x or "").strip().upper()
    if x in ("INFO", "WARN", "WARNING", "ERROR", "ERR", "CRITICAL"):
        if x == "WARNING":
            return "WARN"
        if x == "ERR":
            return "ERROR"
        return x
    return "INFO" if x == "" else x


def build_events_from_status(status_rows: List[dict]) -> Tuple[List[Event], Dict[str, int]]:
    """
    Convert status.csv rows to normalized events.
    We are conservative: only emit for known patterns.
    """
    out: List[Event] = []
    counts: Dict[str, int] = {
        "WORKER_START": 0,
        "WORKER_STOP": 0,
        "POLAR_RESTART": 0,
        "EXCEPTION": 0,
    }

    # Patterns based on your status samples
    re_name = re.compile(r"\bname=(\w+)\b", re.IGNORECASE)
    re_reason = re.compile(r"\breason=([^\s;]+)", re.IGNORECASE)

    for row in status_rows:
        t, lvl, ev, msg = status_extract_fields(row)
        if t is None:
            continue

        ev_l = (ev or "").lower()
        msg_l = (msg or "").lower()
        lvl_n = normalize_level(lvl)

        # worker start/stop
        if "worker_start" in ev_l:
            m = re_name.search(msg)
            name = m.group(1) if m else ""
            out.append(Event(
                t_mono=t, t_wall=row.get("t_wall", "") or "",
                level="INFO", event="WORKER_START", source="status",
                detail=kv_detail(name=name, raw_event=ev, raw_level=lvl_n)
            ))
            counts["WORKER_START"] += 1
            continue

        if "worker_stop" in ev_l:
            m = re_name.search(msg)
            name = m.group(1) if m else ""
            out.append(Event(
                t_mono=t, t_wall=row.get("t_wall", "") or "",
                level="INFO", event="WORKER_STOP", source="status",
                detail=kv_detail(name=name, raw_event=ev, raw_level=lvl_n)
            ))
            counts["WORKER_STOP"] += 1
            continue

        # polar restart
        if "polar_restart" in ev_l or "polar_restart" in msg_l:
            mr = re_reason.search(msg)
            reason = mr.group(1) if mr else ""
            out.append(Event(
                t_mono=t, t_wall=row.get("t_wall", "") or "",
                level="WARN", event="POLAR_RESTART", source="status",
                detail=kv_detail(reason=reason, raw_event=ev, raw_level=lvl_n)
            ))
            counts["POLAR_RESTART"] += 1
            continue

        # exceptions
        # Your sample events: gps_rx_exception, imu_serial_read_exception
        if "exception" in ev_l or "exception" in msg_l:
            out.append(Event(
                t_mono=t, t_wall=row.get("t_wall", "") or "",
                level="WARN" if lvl_n in ("WARN", "INFO") else "ERROR",
                event="EXCEPTION", source="status",
                detail=kv_detail(raw_event=ev, raw_level=lvl_n, message=msg)
            ))
            counts["EXCEPTION"] += 1
            continue

    return out, counts


def build_events_from_unified_state(unified_path: Path) -> Tuple[List[Event], Dict[str, int]]:
    """
    Optional: emit events based on unified.csv where source in (ui,state).
    We keep this minimal and non-invasive.
    """
    out: List[Event] = []
    counts = {"STATE_ROWS": 0, "EMITTED": 0}

    if not unified_path.exists():
        return out, counts

    with unified_path.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            src = (row.get("source") or "").strip()
            if src not in ("ui", "state"):
                continue
            counts["STATE_ROWS"] += 1

            t = safe_float(row.get("t_mono", ""))
            if t is None:
                continue
            name = (row.get("name") or "").strip()
            val = (row.get("value") or "").strip()
            st = (row.get("status") or "").strip()

            # We only pick a few canonical ones if present
            # Examples you may have: START, STOPPING, STOPPED, button_long, etc.
            key = f"{src}.{name}".lower()
            if any(k in key for k in ("start", "stop", "stopping", "stopped", "measure")):
                out.append(Event(
                    t_mono=t,
                    t_wall=(row.get("t_wall") or "").strip(),
                    level="INFO",
                    event="STATE_EVENT",
                    source="unified",
                    detail=kv_detail(source=src, name=name, value=val, status=st)
                ))
                counts["EMITTED"] += 1

    return out, counts


def build_events_from_unified_polar_conn(unified_path: Path) -> Tuple[List[Event], Dict[str, int]]:
    """
    Promote polar connect/disconnect facts in unified.csv to events.
    Looks for:
      source=polar, name=connect, value==1  -> POLAR_CONNECT
      source=polar, name=disconnect, value==1 -> POLAR_DISCONNECT
    """
    out: List[Event] = []
    counts = {"CONNECT": 0, "DISCONNECT": 0}

    if not unified_path.exists():
        return out, counts

    with unified_path.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            if (row.get("source") or "").strip() != "polar":
                continue
            name = (row.get("name") or "").strip()
            if name not in ("connect", "disconnect"):
                continue

            t = safe_float(row.get("t_mono", ""))
            if t is None:
                continue
            tw = (row.get("t_wall") or "").strip()
            v = (row.get("value") or "").strip()

            # accept "1" / "1.0"
            try:
                ok = float(v) == 1.0
            except Exception:
                ok = (v == "1")

            if not ok:
                continue

            if name == "connect":
                out.append(Event(t, tw, "INFO", "POLAR_CONNECT", "unified",
                                 detail=kv_detail(name=name, value=v)))
                counts["CONNECT"] += 1
            else:
                out.append(Event(t, tw, "INFO", "POLAR_DISCONNECT", "unified",
                                 detail=kv_detail(name=name, value=v)))
                counts["DISCONNECT"] += 1

    return out, counts


def read_segment_bounds(seg_path: Path) -> Optional[Tuple[float, float, str]]:
    if not seg_path.exists():
        return None
    try:
        with seg_path.open("r", encoding="utf-8", newline="") as f:
            r = csv.DictReader(f)
            for row in r:
                t0 = safe_float(row.get("t_start", ""))
                t1 = safe_float(row.get("t_end", ""))
                reason = (row.get("reason") or "").strip()
                if t0 is not None and t1 is not None:
                    return t0, t1, reason
    except Exception:
        return None
    return None


def write_events_csv(path: Path, events: List[Event]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["seq", "t_mono", "t_wall", "level", "event", "source", "detail"])
        for i, e in enumerate(events, start=1):
            w.writerow([i, f"{e.t_mono:.6f}", e.t_wall, e.level, e.event, e.source, e.detail])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-root", default=DEFAULT_RUNS_ROOT, help="runs root containing run_*")
    ap.add_argument("--run-dir", default=None, help="explicit run_dir (overrides latest autodetect)")
    ap.add_argument("--print", action="store_true", help="print output paths")
    args = ap.parse_args()

    runs_root = Path(args.runs_root)
    run_dir = Path(args.run_dir) if args.run_dir else find_latest_run(runs_root)

    unified_path = run_dir / "unified.csv"
    status_path = run_dir / "status.csv"
    qc_path = run_dir / "derived" / "qc_report.json"

    derived_dir = run_dir / "derived"
    ensure_dir(derived_dir)
    out_events = derived_dir / "events.csv"
    out_meta = derived_dir / "events_meta.json"

    bounds, berr = scan_unified_bounds(unified_path)
    if bounds is None:
        print(f"ERROR: cannot determine run bounds from unified.csv: {berr}", file=sys.stderr)
        return 2
    t_min, t_max = bounds
    wall_first, wall_last = first_last_wall_times(unified_path)

    events: List[Event] = []

    # Canonical run start/stop (from unified bounds)
    events.append(Event(
        t_mono=t_min, t_wall=wall_first, level="INFO",
        event="RUN_START", source="unified",
        detail=kv_detail(reason="t_mono_min")
    ))
    events.append(Event(
        t_mono=t_max, t_wall=wall_last, level="INFO",
        event="RUN_STOP", source="unified",
        detail=kv_detail(reason="t_mono_max")
    ))

    # From segments_run if present (to anchor measuring interval explicitly)
    seg_run = read_segment_bounds(derived_dir / "segments_run.csv")
    if seg_run:
        s0, s1, rsn = seg_run
        events.append(Event(s0, wall_first, "INFO", "MEASURING_START", "segments", kv_detail(reason=rsn)))
        events.append(Event(s1, wall_last, "INFO", "MEASURING_STOP", "segments", kv_detail(reason=rsn)))


    # QC summary event (optional)
    qc, _ = read_json(qc_path)
    if isinstance(qc, dict):
        overall = qc.get("overall", "")
        events.append(Event(
            t_mono=t_min, t_wall=wall_first, level="INFO",
            event="QC_SUMMARY", source="qc",
            detail=kv_detail(overall=overall, created_at=qc.get("created_at", ""), qc_version=qc.get("qc_version", ""))
        ))

    # Status-derived events
    status_rows = parse_status_rows(status_path)
    ev_status, counts_status = build_events_from_status(status_rows)
    events.extend(ev_status)

    # Unified ui/state optional events
    ev_state, counts_state = build_events_from_unified_state(unified_path)
    events.extend(ev_state)

    # Unified polar connect/disconnect events (recommended)
    ev_polar_conn, counts_polar_conn = build_events_from_unified_polar_conn(unified_path)
    events.extend(ev_polar_conn)


    # Sort by time, then event name
    events.sort(key=lambda e: (e.t_mono, e.event))

    # Write
    write_events_csv(out_events, events)

    meta = {
        "created_at": iso_now(),
        "run_id": run_dir.name,
        "bounds": {"t_min": t_min, "t_max": t_max, "duration_sec": t_max - t_min},
        "counts": {
            "total_events": len(events),
            "status": counts_status,
            "unified_state": counts_state,
        },
        "notes": [
            "RUN_START/STOP are derived from unified.csv t_mono min/max (authoritative bounds).",
            "MEASURING_START/STOP are derived from segments_run.csv if present.",
            "Status-derived events include WORKER_START/STOP, POLAR_RESTART, EXCEPTION (pattern-based).",
            "UI/STATE events from unified are emitted only for start/stop-ish keywords (best-effort).",
        ],
    }
    with out_meta.open("w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    if args.print:
        print(out_events)
        print(out_meta)
    else:
        print(f"{run_dir.name}: wrote {out_events.name} (+ meta) under {derived_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
