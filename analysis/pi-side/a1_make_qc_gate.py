#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
701 Lab QC Gate (run_dir -> qc_report.json + qc_report.md)

Design goals
- Deterministic, lightweight, "facts only"
- No interpolation / no sync estimation / no feature extraction
- Runs on Raspberry Pi 4 (stdlib only)

Usage
  # (NEW) Latest run under default runs_root
  python3 a1_make_qc_gate.py

  # (NEW) Latest run under specified runs_root
  python3 a1_make_qc_gate.py --runs-root /media/seven_zero_one/MF-SU2C/701lab_data/runs

  # Single run (backward compatible)
  python3 a1_make_qc_gate.py /media/seven_zero_one/MF-SU2C/701lab_data/runs/run_20260207_124430_674402

  # All runs under runs_root
  python3 a1_make_qc_gate.py --all /media/seven_zero_one/MF-SU2C/701lab_data/runs

Outputs
  <run_dir>/derived/qc_report.json
  <run_dir>/derived/qc_report.md
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import re
import sys
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


DEFAULT_RUNS_ROOT = "/media/seven_zero_one/MF-SU2C/701lab_data/runs"

# -----------------------------
# Helpers / small utilities
# -----------------------------

LEVEL_OK = "OK"
LEVEL_WARN = "WARN"
LEVEL_FAIL = "FAIL"


def iso_now() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


def safe_float(x: str) -> Optional[float]:
    try:
        v = float(x)
        if math.isfinite(v):
            return v
        return None
    except Exception:
        return None


def safe_int(x: str) -> Optional[int]:
    try:
        return int(float(x))
    except Exception:
        return None


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def find_latest_run(runs_root: Path) -> Path:
    runs = [p for p in runs_root.glob("run_*") if p.is_dir()]
    if not runs:
        raise FileNotFoundError(f"No run_* directories found under {runs_root}")
    runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return runs[0]


@dataclass
class CheckResult:
    level: str
    message: str
    metrics: Dict[str, object]


def combine_overall(levels: List[str]) -> str:
    if any(l == LEVEL_FAIL for l in levels):
        return LEVEL_FAIL
    if any(l == LEVEL_WARN for l in levels):
        return LEVEL_WARN
    return LEVEL_OK


# -----------------------------
# Readers
# -----------------------------

def read_meta(meta_path: Path) -> Tuple[Optional[dict], Optional[str]]:
    if not meta_path.exists():
        return None, f"missing {meta_path.name}"
    try:
        with meta_path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, f"failed to read meta.json: {e}"


def read_unified_stats(unified_path: Path) -> Tuple[Optional[dict], Optional[str]]:
    """
    unified.csv columns (expected):
      seq,t_mono,t_wall,source,name,value,status
    """
    if not unified_path.exists():
        return None, "missing unified.csv"

    stats = {
        "row_count": 0,
        "t_mono_min": None,
        "t_mono_max": None,
        "duration_sec": None,
        "t_mono_monotonic_nondecreasing": True,
        "t_mono_backward_count": 0,
        "sources": {},
        "gps": {
            "has_any": False,
            "fix_rows": 0,
            "fix_1_rows": 0,
            "lat_rows": 0,
            "lon_rows": 0,
            "speed_rows": 0,
        },
        "imu": {
            "has_any": False,
            "written": None,
            "drop": None,
            "timeout": None,
            "bad_checksum_count": None,
            "rx_rate_hz": None,
        },
        "audio": {
            "has_any": False,
            "alive_rows": 0,
            "alive_1_rows": 0,
            "running_rows": 0,
            "running_1_rows": 0,
        },
        "polar": {
            "has_any": False,
        },
    }

    last_t = None
    try:
        with unified_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            required = {"seq", "t_mono", "t_wall", "source", "name", "value", "status"}
            if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
                return None, f"unified.csv header mismatch. found={reader.fieldnames}"

            for row in reader:
                stats["row_count"] += 1

                t = safe_float(row.get("t_mono", ""))
                if t is not None:
                    if stats["t_mono_min"] is None or t < stats["t_mono_min"]:
                        stats["t_mono_min"] = t
                    if stats["t_mono_max"] is None or t > stats["t_mono_max"]:
                        stats["t_mono_max"] = t
                    if last_t is not None and t < last_t:
                        stats["t_mono_monotonic_nondecreasing"] = False
                        stats["t_mono_backward_count"] += 1
                    last_t = t

                src = (row.get("source") or "").strip()
                name = (row.get("name") or "").strip()
                val = (row.get("value") or "").strip()

                if src:
                    stats["sources"][src] = stats["sources"].get(src, 0) + 1

                # GPS
                if src == "gps":
                    stats["gps"]["has_any"] = True
                    if name == "fix":
                        stats["gps"]["fix_rows"] += 1
                        v = safe_int(val)
                        if v == 1:
                            stats["gps"]["fix_1_rows"] += 1
                    elif name == "lat":
                        stats["gps"]["lat_rows"] += 1
                    elif name == "lon":
                        stats["gps"]["lon_rows"] += 1
                    elif name == "speed_mps":
                        stats["gps"]["speed_rows"] += 1

                # IMU health
                if src == "imu":
                    stats["imu"]["has_any"] = True
                    if name in ("written", "drop", "timeout", "bad_checksum_count"):
                        v = safe_int(val)
                        if v is not None:
                            stats["imu"][name] = v
                    elif name == "rx_rate_hz":
                        v = safe_float(val)
                        if v is not None:
                            stats["imu"]["rx_rate_hz"] = v

                # Audio health
                if src == "audio":
                    stats["audio"]["has_any"] = True
                    if name == "alive":
                        stats["audio"]["alive_rows"] += 1
                        v = safe_int(val)
                        if v == 1:
                            stats["audio"]["alive_1_rows"] += 1
                    if name in ("running", "arecord_running"):
                        stats["audio"]["running_rows"] += 1
                        v = safe_int(val)
                        if v == 1:
                            stats["audio"]["running_1_rows"] += 1

                # Polar presence
                if src == "polar":
                    stats["polar"]["has_any"] = True

        if stats["t_mono_min"] is not None and stats["t_mono_max"] is not None:
            stats["duration_sec"] = float(stats["t_mono_max"] - stats["t_mono_min"])
        return stats, None

    except Exception as e:
        return None, f"failed to read unified.csv: {e}"


def scan_status_for_polar_restarts(status_path: Path) -> Tuple[Optional[dict], Optional[str]]:
    if not status_path.exists():
        return None, "missing status.csv"

    out = {
        "polar_restart_mentions": 0,
        "idle_timeout_mentions": 0,
        "exception_mentions": 0,
        "samples": [],
    }

    try:
        with status_path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                low = s.lower()
                hit = False

                if "idle_timeout" in low:
                    out["idle_timeout_mentions"] += 1
                    hit = True
                if "restart" in low and "polar" in low:
                    out["polar_restart_mentions"] += 1
                    hit = True
                if "exception" in low or "traceback" in low:
                    out["exception_mentions"] += 1
                    hit = True

                if hit and len(out["samples"]) < 10:
                    out["samples"].append(s[:300])

        return out, None
    except Exception as e:
        return None, f"failed to read status.csv: {e}"


def audio_wav_meta(wav_path: Path, max_seconds_scan: float = 99999.0) -> Tuple[Optional[dict], Optional[str]]:
    if not wav_path.exists():
        return None, "missing audio.wav"

    try:
        with wave.open(str(wav_path), "rb") as w:
            ch = w.getnchannels()
            sr = w.getframerate()
            nframes = w.getnframes()
            sampwidth = w.getsampwidth()
            comptype = w.getcomptype()

            if comptype != "NONE":
                return None, f"unsupported WAV compression: {comptype}"
            if sampwidth != 2:
                return None, f"unsupported sample width: {sampwidth} (expected 2 bytes = int16)"

            duration = nframes / float(sr) if sr > 0 else None
            if duration is None:
                return None, "invalid sample rate"

            frames_to_scan = nframes
            if max_seconds_scan is not None and max_seconds_scan > 0 and duration > max_seconds_scan:
                frames_to_scan = int(max_seconds_scan * sr)

            chunk = 4096
            total_samples = 0
            sum_abs = 0
            max_abs = 0
            silence = 0
            clip = 0

            w.rewind()
            frames_read = 0
            while frames_read < frames_to_scan:
                need = min(chunk, frames_to_scan - frames_read)
                data = w.readframes(need)
                if not data:
                    break

                a = array("h")
                a.frombytes(data)

                for x in a:
                    ax = abs(int(x))
                    total_samples += 1
                    sum_abs += ax
                    if ax > max_abs:
                        max_abs = ax
                    if ax <= 10:
                        silence += 1
                    if ax >= 32760:
                        clip += 1

                frames_read += need

            mean_abs = (sum_abs / total_samples) if total_samples > 0 else None
            silence_ratio = (silence / total_samples) if total_samples > 0 else None
            clip_ratio = (clip / total_samples) if total_samples > 0 else None

            meta = {
                "path": str(wav_path),
                "channels": ch,
                "sample_rate_hz": sr,
                "frames": nframes,
                "duration_sec": float(duration),
                "scanned_duration_sec": float(frames_to_scan / sr),
                "max_abs": int(max_abs),
                "mean_abs": float(mean_abs) if mean_abs is not None else None,
                "silence_ratio": float(silence_ratio) if silence_ratio is not None else None,
                "clip_ratio": float(clip_ratio) if clip_ratio is not None else None,
            }
            return meta, None

    except wave.Error as e:
        return None, f"WAV read error: {e}"
    except Exception as e:
        return None, f"failed to analyze audio.wav: {e}"


# -----------------------------
# QC checks (policy)
# -----------------------------

def check_run_structure(run_dir: Path) -> CheckResult:
    required = [
        run_dir / "meta" / "meta.json",
        run_dir / "unified.csv",
        run_dir / "status.csv",
    ]
    missing = [str(p.relative_to(run_dir)) for p in required if not p.exists()]
    if missing:
        return CheckResult(
            level=LEVEL_FAIL,
            message=f"Missing required files: {', '.join(missing)}",
            metrics={"missing": missing},
        )
    return CheckResult(LEVEL_OK, "Required files present", {})


def check_unified_core(unified_stats: Optional[dict], unified_err: Optional[str]) -> CheckResult:
    if unified_stats is None:
        return CheckResult(LEVEL_FAIL, f"unified.csv read failed: {unified_err}", {"error": unified_err})
    if unified_stats["row_count"] <= 0:
        return CheckResult(LEVEL_FAIL, "unified.csv has no rows", {"row_count": 0})

    if not unified_stats["t_mono_monotonic_nondecreasing"]:
        return CheckResult(
            LEVEL_FAIL,
            "t_mono is not monotonic non-decreasing (timeline integrity broken)",
            {"t_mono_backward_count": unified_stats.get("t_mono_backward_count", 0)},
        )

    dur = unified_stats.get("duration_sec")
    if dur is None:
        return CheckResult(LEVEL_FAIL, "t_mono min/max not found", {})
    if dur < 5.0:
        return CheckResult(LEVEL_FAIL, f"run duration too short ({dur:.3f} sec)", {"duration_sec": dur})

    return CheckResult(LEVEL_OK, "unified.csv core checks OK", {"duration_sec": dur, "row_count": unified_stats["row_count"]})


def check_gps(unified_stats: Optional[dict]) -> CheckResult:
    if not unified_stats:
        return CheckResult(LEVEL_FAIL, "gps check skipped (no unified stats)", {})

    gps = unified_stats["gps"]
    if not gps["has_any"]:
        return CheckResult(LEVEL_OK, "GPS: no gps rows (likely disabled) → OK", {"gps_present": False})

    fix_rows = gps["fix_rows"]
    fix1 = gps["fix_1_rows"]
    fix_ratio = (fix1 / fix_rows) if fix_rows > 0 else None

    if fix_rows == 0:
        return CheckResult(LEVEL_WARN, "GPS present but no fix rows found", {"fix_rows": 0})

    if fix_ratio is not None and fix_ratio < 0.5:
        return CheckResult(
            LEVEL_WARN,
            f"GPS fix=1 ratio low ({fix_ratio*100:.1f}%)",
            {"fix_ratio": fix_ratio, "fix_rows": fix_rows},
        )

    return CheckResult(
        LEVEL_OK,
        f"GPS fix ratio OK ({fix_ratio*100:.1f}%)" if fix_ratio is not None else "GPS fix ratio N/A",
        {"fix_ratio": fix_ratio, "fix_rows": fix_rows, "lat_rows": gps["lat_rows"], "lon_rows": gps["lon_rows"]},
    )


def check_imu_health(unified_stats: Optional[dict]) -> CheckResult:
    if not unified_stats:
        return CheckResult(LEVEL_FAIL, "imu check skipped (no unified stats)", {})

    imu = unified_stats["imu"]
    if not imu["has_any"]:
        return CheckResult(LEVEL_OK, "IMU: no imu rows (likely disabled) → OK", {"imu_present": False})

    metrics = {
        "written": imu.get("written"),
        "drop": imu.get("drop"),
        "timeout": imu.get("timeout"),
        "bad_checksum_count": imu.get("bad_checksum_count"),
        "rx_rate_hz": imu.get("rx_rate_hz"),
    }

    warn_msgs = []
    for k in ("drop", "timeout", "bad_checksum_count"):
        v = imu.get(k)
        if isinstance(v, int) and v > 0:
            warn_msgs.append(f"{k}={v}")

    if warn_msgs:
        return CheckResult(LEVEL_WARN, "IMU health warnings: " + ", ".join(warn_msgs), metrics)

    return CheckResult(LEVEL_OK, "IMU health OK (no drop/timeout/checksum errors)", metrics)


def check_audio(run_dir: Path, unified_stats: Optional[dict]) -> CheckResult:
    wav_path = run_dir / "raw" / "audio.wav"
    meta, err = audio_wav_meta(wav_path)

    if meta is None:
        audio_present = bool(unified_stats and unified_stats.get("audio", {}).get("has_any"))
        if audio_present:
            return CheckResult(LEVEL_WARN, f"Audio rows exist in unified but audio.wav missing: {err}", {"error": err})
        return CheckResult(LEVEL_WARN, f"audio.wav not available: {err}", {"error": err})

    dur_run = unified_stats.get("duration_sec") if unified_stats else None
    dur_wav = meta.get("duration_sec")
    metrics = dict(meta)
    metrics["run_duration_sec"] = dur_run

    silence_ratio = meta.get("silence_ratio")
    clip_ratio = meta.get("clip_ratio")

    warn = []
    if dur_run is not None and dur_wav is not None:
        diff = abs(dur_wav - dur_run)
        metrics["duration_diff_sec"] = diff
        if diff > 3.0 and diff > 0.1 * max(dur_run, 1e-6):
            warn.append(f"duration mismatch (wav={dur_wav:.2f}s vs run={dur_run:.2f}s)")

    if silence_ratio is not None and silence_ratio > 0.80:
        warn.append(f"high silence ratio ({silence_ratio*100:.1f}%)")
    if clip_ratio is not None and clip_ratio > 0.01:
        warn.append(f"clipping detected ({clip_ratio*100:.2f}%)")

    if warn:
        return CheckResult(LEVEL_WARN, "Audio warnings: " + "; ".join(warn), metrics)

    return CheckResult(LEVEL_OK, "Audio OK (basic stats)", metrics)


def check_status(status_scan: Optional[dict], status_err: Optional[str]) -> CheckResult:
    if status_scan is None:
        return CheckResult(LEVEL_FAIL, f"status.csv read failed: {status_err}", {"error": status_err})

    idle = status_scan.get("idle_timeout_mentions", 0)
    polar_restart = status_scan.get("polar_restart_mentions", 0)
    exc = status_scan.get("exception_mentions", 0)

    metrics = dict(status_scan)

    msg_parts = []
    level = LEVEL_OK

    if polar_restart > 0 or idle > 0:
        level = LEVEL_WARN
        msg_parts.append(f"Polar restarts/idle_timeout detected (restart={polar_restart}, idle_timeout={idle})")

    if exc > 0:
        level = LEVEL_WARN
        msg_parts.append(f"Exceptions mentioned in status (count={exc})")

    if not msg_parts:
        return CheckResult(LEVEL_OK, "status.csv OK (no notable issues found by scan)", metrics)

    return CheckResult(level, " / ".join(msg_parts), metrics)


# -----------------------------
# Report writers
# -----------------------------

def write_qc_json(path: Path, report: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


def write_qc_md(path: Path, report: dict) -> None:
    checks: Dict[str, dict] = report.get("checks", {})
    overall = report.get("overall", "UNKNOWN")
    run_id = report.get("run_id", "")
    run_dir = report.get("run_dir", "")
    created_at = report.get("created_at", "")

    lines: List[str] = []
    lines.append(f"# QC Report: {run_id}")
    lines.append("")
    lines.append(f"- Created: {created_at}")
    lines.append(f"- Run dir: `{run_dir}`")
    lines.append(f"- Overall: **{overall}**")
    lines.append("")

    summary = report.get("summary", {})
    if summary:
        lines.append("## Summary")
        for k, v in summary.items():
            lines.append(f"- {k}: {v}")
        lines.append("")

    lines.append("## Checks")
    for name, c in checks.items():
        lvl = c.get("level", "UNKNOWN")
        msg = c.get("message", "")
        lines.append(f"### {name}")
        lines.append(f"- Result: **{lvl}**")
        lines.append(f"- Message: {msg}")
        metrics = c.get("metrics", {})
        if metrics:
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(metrics, ensure_ascii=False, indent=2))
            lines.append("```")
        lines.append("")

    status_metrics = checks.get("status_scan", {}).get("metrics", {})
    samples = status_metrics.get("samples", [])
    if samples:
        lines.append("## Status samples (first 10 hits)")
        for s in samples:
            lines.append(f"- {s}")
        lines.append("")

    with path.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# -----------------------------
# Main QC flow
# -----------------------------

def qc_one_run(run_dir: Path) -> Tuple[dict, str]:
    run_dir = run_dir.resolve()
    run_id = run_dir.name

    derived_dir = run_dir / "derived"
    ensure_dir(derived_dir)

    meta_path = run_dir / "meta" / "meta.json"
    unified_path = run_dir / "unified.csv"
    status_path = run_dir / "status.csv"

    meta, meta_err = read_meta(meta_path)
    unified_stats, unified_err = read_unified_stats(unified_path)
    status_scan, status_err = scan_status_for_polar_restarts(status_path)

    checks: Dict[str, CheckResult] = {}
    checks["run_structure"] = check_run_structure(run_dir)
    checks["unified_core"] = check_unified_core(unified_stats, unified_err)
    checks["gps_quality"] = check_gps(unified_stats)
    checks["imu_health"] = check_imu_health(unified_stats)
    checks["audio_basic"] = check_audio(run_dir, unified_stats)
    checks["status_scan"] = check_status(status_scan, status_err)

    levels = [c.level for c in checks.values()]
    overall = combine_overall(levels)

    duration = unified_stats.get("duration_sec") if unified_stats else None
    sources = sorted((unified_stats.get("sources", {}) if unified_stats else {}).keys())
    summary = {
        "duration_sec": duration,
        "row_count_unified": unified_stats.get("row_count") if unified_stats else None,
        "sources_in_unified": sources,
        "meta_present": meta is not None,
        "meta_error": meta_err,
        "unified_error": unified_err,
        "status_error": status_err,
    }

    report = {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "created_at": iso_now(),
        "qc_version": "0.1",
        "overall": overall,
        "summary": summary,
        "checks": {
            name: {"level": cr.level, "message": cr.message, "metrics": cr.metrics}
            for name, cr in checks.items()
        },
    }

    qc_json_path = derived_dir / "qc_report.json"
    qc_md_path = derived_dir / "qc_report.md"
    write_qc_json(qc_json_path, report)
    write_qc_md(qc_md_path, report)

    return report, str(qc_md_path)


def list_runs(runs_root: Path) -> List[Path]:
    runs = []
    if not runs_root.exists():
        return runs
    for p in sorted(runs_root.iterdir()):
        if p.is_dir() and p.name.startswith("run_"):
            runs.append(p)
    return runs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=None,
                    help="(optional) run_dir or runs_root. If omitted, latest run under --runs-root is used.")
    ap.add_argument("--runs-root", default=DEFAULT_RUNS_ROOT, help="runs root containing run_*")
    ap.add_argument("--run-dir", default=None, help="explicit run_dir (overrides path/latest)")
    ap.add_argument("--all", action="store_true", help="process all run_* dirs under runs_root (path or --runs-root)")
    ap.add_argument("--print", action="store_true", help="print markdown path after processing")
    args = ap.parse_args()

    runs_root = Path(args.runs_root)

    # Resolve target(s)
    if args.all:
        # Determine root to scan: path (if provided) else --runs-root
        root = Path(args.path) if args.path else runs_root
        runs = list_runs(root)
        if not runs:
            print(f"No run_* directories found under: {root}")
            return 2

        ok = warn = fail = 0
        for r in runs:
            report, md_path = qc_one_run(r)
            overall = report.get("overall")
            if overall == LEVEL_OK:
                ok += 1
            elif overall == LEVEL_WARN:
                warn += 1
            else:
                fail += 1
            print(f"{r.name}: {overall} -> {md_path}")

        print(f"\nSummary: OK={ok} WARN={warn} FAIL={fail} (total={len(runs)})")
        return 0

    # Single run mode
    if args.run_dir:
        run_dir = Path(args.run_dir)
    elif args.path:
        run_dir = Path(args.path)
        # If user accidentally passed runs_root without --all, interpret as "latest under that root"
        if run_dir.exists() and run_dir.is_dir() and run_dir.name != "run_" and run_dir.name.startswith("run_") is False:
            # Heuristic: if it contains run_* dirs, treat as root
            if any(p.is_dir() and p.name.startswith("run_") for p in run_dir.iterdir()):
                run_dir = find_latest_run(run_dir)
    else:
        run_dir = find_latest_run(runs_root)

    if not run_dir.exists() or not run_dir.is_dir():
        print(f"Not a directory: {run_dir}")
        return 2

    report, md_path = qc_one_run(run_dir)
    if args.print:
        print(md_path)
    else:
        print(f"{run_dir.name}: {report.get('overall')} (written: {md_path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
