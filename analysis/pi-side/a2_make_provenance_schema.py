#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
701 Lab A2: Provenance / Schema generator (run_dir -> derived/schema.json + derived/provenance.json)

- Finds latest run_* under runs_root (default: /media/seven_zero_one/MF-SU2C/701lab_data/runs)
- Reads meta/meta.json, unified.csv header, status.csv existence
- Optionally reads derived/qc_report.json if present
- Writes:
    <run_dir>/derived/schema.json
    <run_dir>/derived/provenance.json

Usage:
  python3 a2_make_provenance_schema.py
  python3 a2_make_provenance_schema.py --runs-root /media/seven_zero_one/MF-SU2C/701lab_data/runs
  python3 a2_make_provenance_schema.py --run-dir /path/to/run_xxx   # override latest autodetect
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import platform
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple


DEFAULT_RUNS_ROOT = "/media/seven_zero_one/MF-SU2C/701lab_data/runs"


def iso_now() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def read_json(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    if not path.exists():
        return None, f"missing: {path}"
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, f"failed to read json: {path} err={e}"


def read_csv_header(path: Path) -> Tuple[Optional[list], Optional[str]]:
    if not path.exists():
        return None, f"missing: {path}"
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                return None, f"empty csv: {path}"
            return header, None
    except Exception as e:
        return None, f"failed to read csv header: {path} err={e}"


def find_latest_run(runs_root: Path) -> Path:
    # latest by directory mtime-ish: use sorted by name but safer with glob + stat
    candidates = [p for p in runs_root.glob("run_*") if p.is_dir()]
    if not candidates:
        raise FileNotFoundError(f"No run_* directories found under {runs_root}")
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def write_json(path: Path, obj: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def infer_time_base_from_unified_header(header: list) -> dict:
    # For now, we fix the contract: t_mono is authoritative.
    return {
        "key": "t_mono",
        "unit": "second",
        "authoritative": True,
        "notes": "t_mono is the analysis time base (monotonic).",
    }


def build_schema(run_id: str, unified_header: list) -> dict:
    """
    Minimal, stable schema.
    - Defines unified.csv table contract
    - Defines derived outputs contract placeholders (qc_report, events, segments)
    """
    # unified fixed columns expected
    # We'll store what we observed and what we expect.
    expected = ["seq", "t_mono", "t_wall", "source", "name", "value", "status"]

    schema = {
        "schema_version": "0.1",
        "run_id": run_id,
        "created_at": iso_now(),
        "time_base": infer_time_base_from_unified_header(unified_header),
        "tables": {
            "unified": {
                "path": "unified.csv",
                "description": "Fact log (index/timeline dictionary).",
                "observed_header": unified_header,
                "expected_header": expected,
                "columns": {
                    "seq": {"type": "int", "unit": "count", "notes": "Monotonic sequence number."},
                    "t_mono": {"type": "float", "unit": "s", "notes": "Monotonic time (authoritative)."},
                    "t_wall": {"type": "str", "unit": "ISO8601", "notes": "Wall clock time (reference)."},
                    "source": {"type": "str", "notes": "Sensor/source name (gps/temp/imu/audio/polar/ui/state/...)."},
                    "name": {"type": "str", "notes": "Measurement name within source."},
                    "value": {"type": "str", "notes": "Raw value (string); downstream casts by (source,name)."},
                    "status": {"type": "str", "notes": "OK/WARN/ERR or vendor status."},
                },
                "missing_policy": {
                    "rows": "No interpolation at this stage. Missing facts remain missing.",
                    "value": "Kept as empty string if missing in CSV row.",
                },
            },
            "status": {
                "path": "status.csv",
                "description": "Event/exception log for debugging and QC.",
                "notes": "Schema may vary; parsed by pattern scanning in early pipeline.",
            },
            "meta": {
                "path": "meta/meta.json",
                "description": "Run context snapshot (env/config, start/stop, devices).",
                "notes": "Primary source for enabled sensors and experimental conditions.",
            },

            # Derived contracts (A1/A3/A4 etc.) - placeholders to be filled as you implement
            "qc_report": {
                "path": "derived/qc_report.json",
                "description": "Quality gate output (OK/WARN/FAIL + metrics).",
                "notes": "Generated by qc_gate.py",
            },
            "segments": {
                "path_glob": "derived/segments_*.csv",
                "description": "Valid segments per sensor (t_mono start/end + reason).",
                "columns": {
                    "t_start": {"type": "float", "unit": "s"},
                    "t_end": {"type": "float", "unit": "s"},
                    "reason": {"type": "str"},
                },
            },
            "events": {
                "path": "derived/events.csv",
                "description": "Normalized run events (START/STOP/RESTART...).",
                "notes": "To be generated from unified/status.",
            },
        },
    }
    return schema


def build_provenance(
    run_dir: Path,
    meta: Optional[dict],
    qc: Optional[dict],
    hashes: Dict[str, dict],
    tool_name: str,
    tool_version: str,
    command_line: str,
) -> dict:
    run_id = run_dir.name

    # Extract a few useful meta pieces if available (don’t assume exact keys)
    meta_summary = {}
    if isinstance(meta, dict):
        # Common keys you might have; if absent, we keep it light.
        for k in ("run_id", "t_mono_start", "t_mono_end", "t_wall_start", "t_wall_end", "env", "devices"):
            if k in meta:
                meta_summary[k] = meta[k]

    qc_summary = {}
    if isinstance(qc, dict):
        qc_summary = {
            "overall": qc.get("overall"),
            "created_at": qc.get("created_at"),
            "qc_version": qc.get("qc_version"),
        }

    prov = {
        "provenance_version": "0.1",
        "run_id": run_id,
        "run_dir": str(run_dir),
        "created_at": iso_now(),
        "tool": {
            "name": tool_name,
            "version": tool_version,
            "command": command_line,
        },
        "host": {
            "node": platform.node(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": sys.version.split()[0],
        },
        "inputs": hashes,  # path -> sha256/size/mtime
        "meta_summary": meta_summary,
        "qc_summary": qc_summary,
        "notes": [
            "Raw and primary logs (meta/unified/status/raw/*) must be treated read-only.",
            "Derived artifacts are written only under run_dir/derived/.",
        ],
    }
    return prov


def collect_input_hashes(run_dir: Path) -> Dict[str, dict]:
    """
    Hash only the key small/medium files by default:
      - meta/meta.json
      - unified.csv
      - status.csv
      - raw/audio.wav (can be large, but hashing is still ok; if you want faster, disable)
      - raw/imu_bwt901cl.bin (can be large; default: do NOT hash, just record stat)
    """
    items = {}

    def add(path_rel: str, do_hash: bool) -> None:
        p = run_dir / path_rel
        if not p.exists():
            items[path_rel] = {"exists": False}
            return
        st = p.stat()
        rec = {
            "exists": True,
            "size_bytes": int(st.st_size),
            "mtime": dt.datetime.fromtimestamp(st.st_mtime).replace(microsecond=0).isoformat(),
        }
        if do_hash:
            rec["sha256"] = sha256_file(p)
        items[path_rel] = rec

    add("meta/meta.json", True)
    add("unified.csv", True)
    add("status.csv", True)
    add("raw/audio.wav", True)            # moderate usually
    add("raw/imu_bwt901cl.bin", False)    # potentially big; stat only by default

    # If already exists, include qc_report too (to anchor pipeline state)
    add("derived/qc_report.json", True)

    return items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-root", default=DEFAULT_RUNS_ROOT, help="runs root directory containing run_*")
    ap.add_argument("--run-dir", default=None, help="explicit run_dir (overrides latest autodetect)")
    ap.add_argument("--tool-version", default="0.1", help="version string for this script")
    ap.add_argument("--print", action="store_true", help="print output paths")
    args = ap.parse_args()

    runs_root = Path(args.runs_root)
    if args.run_dir:
        run_dir = Path(args.run_dir)
    else:
        run_dir = find_latest_run(runs_root)

    if not run_dir.exists() or not run_dir.is_dir():
        print(f"ERROR: run_dir not found: {run_dir}")
        return 2

    run_id = run_dir.name

    meta_path = run_dir / "meta" / "meta.json"
    unified_path = run_dir / "unified.csv"
    qc_path = run_dir / "derived" / "qc_report.json"

    unified_header, uerr = read_csv_header(unified_path)
    if unified_header is None:
        print(f"ERROR: cannot read unified.csv header: {uerr}")
        return 2

    meta, _ = read_json(meta_path)
    qc, _ = read_json(qc_path)  # optional

    # outputs
    derived_dir = run_dir / "derived"
    ensure_dir(derived_dir)
    out_schema = derived_dir / "schema.json"
    out_prov = derived_dir / "provenance.json"

    schema = build_schema(run_id, unified_header)

    hashes = collect_input_hashes(run_dir)
    prov = build_provenance(
        run_dir=run_dir,
        meta=meta,
        qc=qc,
        hashes=hashes,
        tool_name="a2_make_provenance_schema.py",
        tool_version=args.tool_version,
        command_line=" ".join(sys.argv),
    )

    write_json(out_schema, schema)
    write_json(out_prov, prov)

    if args.print:
        print(str(out_schema))
        print(str(out_prov))
    else:
        print(f"{run_id}: wrote {out_schema.name}, {out_prov.name} under {derived_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
