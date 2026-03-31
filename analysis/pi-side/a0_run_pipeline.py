#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
701 Lab A0: Pi-side pipeline orchestrator (A1..A5) + (optional) Windows transfer (Method B: _incoming)

Method B policy (recommended)
- Pi writes ONLY to Windows-side "_incoming" area.
- Pi NEVER writes into Windows "immutable/".
- Windows later moves verified incoming payloads into immutable/ and locks them read-only.

Windows-side expected structure (on D:)
D:/701lab/
  _incoming/
    runs/
      run_YYYYMMDD_HHMMSS_xxxxxx/
      ...
    runs_index.csv            # optional (Pi can drop here)
    incoming_ready.json       # optional (per-run marker is created inside run)

Pi-side mount example
/mnt/win701lab  ->  /WINPC/701lab  (SMB mount)
Then:
  --win-mount-root /mnt/win701lab
  --win-incoming-dir /mnt/win701lab/_incoming

What this script does
- Runs A1..A5 for a target run (latest by default).
- Optional transfer gate:
    mount check -> transfer to _incoming/runs/<run_id> -> verify -> write marker -> log

Notes
- Uses stdlib only. (rsync method requires rsync command)
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DEFAULT_RUNS_ROOT = "/media/seven_zero_one/MF-SU2C/701lab_data/runs"


def iso_now() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


# ===== CSV logging =====

def append_csv_row(path: Path, header: List[str], row: Dict[str, object]) -> None:
    ensure_dir(path.parent)
    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        if write_header:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in header})


# ===== Mount check helpers =====

def read_proc_mounts() -> List[Tuple[str, str]]:
    """Return list of (mount_point, fs_type) from /proc/mounts (deepest first)."""
    mounts: List[Tuple[str, str]] = []
    try:
        with open("/proc/mounts", "r", encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 3:
                    mnt = parts[1]
                    fst = parts[2]
                    mounts.append((mnt, fst))
    except Exception:
        pass
    mounts.sort(key=lambda x: len(x[0]), reverse=True)
    return mounts


def is_path_under_mounted_fs(path: Path) -> Tuple[bool, str]:
    """Determine whether 'path' is under a mounted filesystem (best-effort)."""
    try:
        p = str(path.resolve())
    except Exception:
        p = str(path)

    for mnt, _fst in read_proc_mounts():
        if p == mnt or p.startswith(mnt.rstrip("/") + "/"):
            return True, mnt
    return False, ""


def assert_windows_share_mounted(win_root: Path, must_be_mounted: bool = True) -> Tuple[bool, str]:
    """
    Safety gate: ensure win_root exists AND is under a mounted filesystem.
    Prevents accidental mkdir/copy to local filesystem when mount is missing.
    """
    if not win_root.exists():
        return False, f"win_root does not exist: {win_root} (mount missing?)"

    ok, mnt = is_path_under_mounted_fs(win_root)
    if must_be_mounted and not ok:
        return False, f"win_root is not under any mount in /proc/mounts: {win_root}"
    return True, f"mounted_under={mnt or 'unknown'}"


# ===== Transfer verification =====

def dir_stats(root: Path) -> Dict[str, int]:
    """Directory stats: file_count, dir_count, total_bytes"""
    file_count = 0
    dir_count = 0
    total_bytes = 0
    for dpath, dnames, fnames in os.walk(root):
        dir_count += len(dnames)
        for fn in fnames:
            fp = Path(dpath) / fn
            try:
                st = fp.stat()
                file_count += 1
                total_bytes += int(st.st_size)
            except Exception:
                pass
    return {"file_count": file_count, "dir_count": dir_count, "total_bytes": total_bytes}


def verify_transfer(src_run: Path, dst_run: Path) -> Tuple[bool, str, Dict[str, object]]:
    """
    Verify:
      - required files exist at destination
      - key file sizes match
      - total_bytes match (best-effort)
    """
    required = [
        "meta/meta.json",
        "unified.csv",
        "status.csv",
        "derived/qc_report.json",
        "derived/provenance.json",
        "derived/schema.json",
        "derived/segments_meta.json",
        "derived/events.csv",
    ]
    missing = [rel for rel in required if not (dst_run / rel).exists()]
    if missing:
        return False, f"missing required files at dest: {', '.join(missing)}", {"missing": missing}

    key_files = [
        "meta/meta.json",
        "unified.csv",
        "status.csv",
        "derived/qc_report.json",
        "derived/events.csv",
    ]
    mism = []
    for rel in key_files:
        s = src_run / rel
        d = dst_run / rel
        try:
            if s.stat().st_size != d.stat().st_size:
                mism.append(rel)
        except Exception:
            mism.append(rel)
    if mism:
        return False, f"size mismatch for: {', '.join(mism)}", {"size_mismatch": mism}

    try:
        st_src = dir_stats(src_run)
        st_dst = dir_stats(dst_run)
        if st_src["total_bytes"] != st_dst["total_bytes"]:
            return False, "total_bytes mismatch (partial copy suspected)", {"src_stats": st_src, "dst_stats": st_dst}
        return True, "verified", {"src_stats": st_src, "dst_stats": st_dst}
    except Exception as e:
        # Not fatal: keep verified with warning if stats failed
        return True, f"verified (warning: stats check skipped: {e})", {}


def safe_copytree(src: Path, dst: Path) -> Tuple[bool, str]:
    """Copy src dir to dst dir. Fail if dst exists (immutable-like rule for incoming)."""
    if dst.exists():
        return False, "dest already exists (skip)"
    try:
        shutil.copytree(src, dst)
        return True, "copied"
    except Exception as e:
        return False, f"copytree failed: {e}"


def _write_transfer_logs(run_dir: Path, runs_root: Path, result: Dict[str, object]) -> None:
    # Per-run transfer meta (on Pi side)
    tm = run_dir / "derived" / "transfer_meta.json"
    try:
        ensure_dir(tm.parent)
        with tm.open("w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # Global transfer log (on Pi side)
    try:
        log_path = runs_root / "derived" / "transfer_log.csv"
        header = [
            "ended_at", "run_id", "status", "method",
            "src_run_dir", "dest_run_dir", "message",
            "mount_checked", "mount_ok",
            "verify_ok",
        ]
        append_csv_row(log_path, header, {
            "ended_at": result.get("ended_at", ""),
            "run_id": result.get("run_id", ""),
            "status": result.get("status", ""),
            "method": result.get("method", ""),
            "src_run_dir": result.get("src_run_dir", ""),
            "dest_run_dir": result.get("dest_run_dir", ""),
            "message": result.get("message", ""),
            "mount_checked": (result.get("mount_check") or {}).get("checked", ""),
            "mount_ok": (result.get("mount_check") or {}).get("ok", ""),
            "verify_ok": (result.get("verify") or {}).get("ok", ""),
        })
    except Exception:
        pass


def _write_incoming_marker(dest_run: Path, result: Dict[str, object]) -> None:
    """
    Write a marker file INSIDE the incoming run directory.
    Windows can move-to-immutable only when this exists and says OK.
    """
    marker = dest_run / "_INCOMING_OK.json"
    payload = {
        "schema": "701lab_incoming_marker_v1",
        "created_at": iso_now(),
        "transfer": {
            "run_id": result.get("run_id"),
            "status": result.get("status"),
            "message": result.get("message"),
            "method": result.get("method"),
            "src_run_dir": result.get("src_run_dir"),
            "dest_run_dir": result.get("dest_run_dir"),
            "verify": result.get("verify"),
        }
    }
    try:
        with marker.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        # If marker cannot be written, treat as warning (but you might prefer to treat as NG)
        pass


def transfer_run_to_incoming(
    run_dir: Path,
    runs_root: Path,
    win_incoming_dir: Path,
    win_root_for_mount_check: Optional[Path],
    method: str = "copytree",
    transfer_runs_index: bool = True,
    quiet: bool = False,
) -> Dict[str, object]:
    """
    Method B: Windows incoming transfer

    Mount check -> transfer to:
        <win_incoming_dir>/runs/<run_id>
    Verify -> write marker inside dest run -> logs (Pi side)
    """
    started = iso_now()
    run_id = run_dir.name

    incoming_runs = win_incoming_dir / "runs"
    dest_run = incoming_runs / run_id

    result: Dict[str, object] = {
        "run_id": run_id,
        "src_run_dir": str(run_dir),
        "dest_run_dir": str(dest_run),
        "method": method,
        "started_at": started,
        "ended_at": None,
        "status": "NG",
        "message": "",
        "rc": None,
        "mount_check": None,
        "verify": None,
        "warnings": [],
        "mode": "method_B_incoming",
        "incoming_dir": str(win_incoming_dir),
    }

    # ---- Mount check (HARD GATE) ----
    chk_target = (win_root_for_mount_check or win_incoming_dir)
    ok, msg = assert_windows_share_mounted(chk_target, must_be_mounted=True)
    result["mount_check"] = {"ok": ok, "msg": msg, "checked": str(chk_target)}
    if not ok:
        result["status"] = "NG"
        result["message"] = f"mount check failed: {msg}"
        result["ended_at"] = iso_now()
        _write_transfer_logs(run_dir, runs_root, result)
        return result

    # Only now we allow mkdir under win_incoming_dir
    try:
        ensure_dir(incoming_runs)
    except Exception as e:
        result["status"] = "NG"
        result["message"] = f"failed to ensure incoming_runs dir: {e}"
        result["ended_at"] = iso_now()
        _write_transfer_logs(run_dir, runs_root, result)
        return result

    # ---- Transfer ----
    try:
        if method == "copytree":
            ok2, msg2 = safe_copytree(run_dir, dest_run)
            result["status"] = "OK" if ok2 else "SKIP"
            result["message"] = msg2
            result["rc"] = 0

        elif method == "rsync":
            # For rsync we create dest dir (safe; still under mount-checked path)
            dest_run.mkdir(parents=True, exist_ok=True)
            cmd = ["rsync", "-a", "--ignore-existing", str(run_dir) + "/", str(dest_run) + "/"]
            rc = run_cmd(cmd, quiet=quiet)
            result["rc"] = rc
            if rc == 0:
                result["status"] = "OK"
                result["message"] = "rsync complete"
            else:
                result["status"] = "NG"
                result["message"] = f"rsync failed rc={rc}"
        else:
            raise ValueError(f"unknown transfer method: {method}")

        # Verify (OK or SKIP)
        if result["status"] in ("OK", "SKIP"):
            v_ok, v_msg, v_meta = verify_transfer(run_dir, dest_run)
            result["verify"] = {"ok": v_ok, "msg": v_msg, "meta": v_meta}
            if not v_ok and result["status"] == "OK":
                result["status"] = "NG"
                result["message"] = f"{result['message']} / verify failed: {v_msg}"
            elif not v_ok and result["status"] == "SKIP":
                result["warnings"].append(f"verify failed on existing dest: {v_msg}")

        # If final is OK and verified OK -> write marker in incoming run dir
        if result["status"] == "OK" and (result.get("verify") or {}).get("ok") is True:
            _write_incoming_marker(dest_run, result)

        # Copy runs_index.csv to incoming (NOT immutable) (best effort)
        if transfer_runs_index:
            src_index = runs_root / "derived" / "runs_index.csv"
            dst_index = win_incoming_dir / "runs_index.csv"
            if src_index.exists():
                try:
                    shutil.copy2(src_index, dst_index)
                except Exception as e:
                    result["warnings"].append(f"runs_index copy failed: {e}")
            else:
                result["warnings"].append("runs_index.csv not found at runs_root/derived")

    except Exception as e:
        result["status"] = "NG"
        result["message"] = str(e)

    result["ended_at"] = iso_now()
    _write_transfer_logs(run_dir, runs_root, result)
    return result


# ===== Existing A0 pipeline helpers =====

def find_latest_run(runs_root: Path) -> Path:
    runs = [p for p in runs_root.glob("run_*") if p.is_dir()]
    if not runs:
        raise FileNotFoundError(f"No run_* directories found under {runs_root}")
    runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return runs[0]


def mtime(path: Path) -> Optional[float]:
    try:
        return path.stat().st_mtime if path.exists() else None
    except Exception:
        return None


def read_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def run_cmd(cmd: List[str], cwd: Optional[Path] = None, quiet: bool = False) -> int:
    if not quiet:
        print("+", " ".join(cmd))
    try:
        p = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if not quiet:
            out = (p.stdout or "").rstrip()
            if out:
                print(out)
        return int(p.returncode)
    except FileNotFoundError as e:
        print(f"ERROR: command not found: {e}", file=sys.stderr)
        return 127
    except Exception as e:
        print(f"ERROR: failed to run command: {e}", file=sys.stderr)
        return 126


def stale_summary(run_dir: Path) -> Dict[str, object]:
    inputs = {
        "meta/meta.json": run_dir / "meta" / "meta.json",
        "unified.csv": run_dir / "unified.csv",
        "status.csv": run_dir / "status.csv",
    }

    derived = {
        "derived/qc_report.json": run_dir / "derived" / "qc_report.json",
        "derived/provenance.json": run_dir / "derived" / "provenance.json",
        "derived/schema.json": run_dir / "derived" / "schema.json",
        "derived/segments_meta.json": run_dir / "derived" / "segments_meta.json",
        "derived/events.csv": run_dir / "derived" / "events.csv",
        "derived/runs_index.csv": run_dir.parent / "derived" / "runs_index.csv",
    }

    in_m = {k: mtime(p) for k, p in inputs.items()}
    dr_m = {k: mtime(p) for k, p in derived.items()}

    newest_in = max((v for v in in_m.values() if v is not None), default=None)
    oldest_dr = min((v for v in dr_m.values() if v is not None), default=None)

    missing = [k for k, v in dr_m.items() if v is None]
    if missing:
        return {
            "inputs_mtime": in_m,
            "derived_mtime": dr_m,
            "newest_input_mtime": newest_in,
            "oldest_derived_mtime": oldest_dr,
            "stale": True,
            "reason": f"missing derived outputs: {', '.join(missing)}",
        }

    if newest_in is not None and oldest_dr is not None and newest_in > oldest_dr:
        stale = True
        reason = "some inputs are newer than derived outputs"
    else:
        stale = False
        reason = "derived outputs look fresh"

    return {
        "inputs_mtime": in_m,
        "derived_mtime": dr_m,
        "newest_input_mtime": newest_in,
        "oldest_derived_mtime": oldest_dr,
        "stale": stale,
        "reason": reason,
    }


def wipe_derived(run_dir: Path) -> None:
    d = run_dir / "derived"
    if not d.exists():
        return
    for name in [
        "qc_report.json", "qc_report.md",
        "schema.json", "provenance.json",
        "segments_run.csv", "segments_gps.csv", "segments_audio.csv",
        "segments_polar.csv", "segments_imu.csv", "segments_meta.json",
        "events.csv", "events_meta.json",
        "pipeline_meta.json", "transfer_meta.json",
    ]:
        p = d / name
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass


def script_path(scripts_dir: Path, name: str) -> Path:
    return scripts_dir / name


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-root", default=DEFAULT_RUNS_ROOT, help="runs root containing run_*")
    ap.add_argument("--run-dir", default=None, help="explicit run_dir (overrides latest autodetect)")
    ap.add_argument("--scripts-dir", default=None, help="directory containing a1..a5 scripts (default: this file's dir)")
    ap.add_argument("--python", default=sys.executable, help="python executable to run steps")
    ap.add_argument("--wipe-derived", action="store_true", help="wipe known derived outputs under run_dir/derived before running")
    ap.add_argument("--skip-stale-check", action="store_true", help="do not check freshness; just run pipeline")
    ap.add_argument("--continue-on-fail", action="store_true", help="continue even if A1 overall is FAIL")
    ap.add_argument("--quiet", action="store_true", help="reduce step stdout (still prints commands)")
    ap.add_argument("--print-run-dir", action="store_true", help="print resolved run_dir and exit")
    ap.add_argument("--print", action="store_true", help="print key output paths at end")

    # ---- Windows transfer options (Method B: _incoming) ----
    ap.add_argument("--win-incoming-dir", default=None,
                    help="Piから見えるWindows側 _incoming のパス。指定すると _incoming/runs/<run_id> に転送する")
    ap.add_argument("--win-mount-root", default=None,
                    help="マウント確認用のルート（例: /mnt/win701lab）。省略時は win-incoming-dir 自体をチェック")
    ap.add_argument("--transfer-method", default="copytree", choices=["copytree", "rsync"],
                    help="transfer method (copytree: stdlib, rsync: faster)")
    ap.add_argument("--transfer-on-qc", default="ANY", choices=["ANY", "OK", "WARN", "FAIL"],
                    help="qc_overall gate for transfer")
    ap.add_argument("--transfer-runs-index", action="store_true",
                    help="also copy runs_index.csv to Windows _incoming/ (NOT immutable)")

    args = ap.parse_args()

    runs_root = Path(args.runs_root)
    if not runs_root.exists():
        print(f"ERROR: runs_root not found: {runs_root}", file=sys.stderr)
        return 2

    scripts_dir = Path(args.scripts_dir) if args.scripts_dir else Path(__file__).resolve().parent

    run_dir = Path(args.run_dir) if args.run_dir else find_latest_run(runs_root)
    run_dir = run_dir.resolve()

    if args.print_run_dir:
        print(str(run_dir))
        return 0

    if not run_dir.exists() or not run_dir.is_dir():
        print(f"ERROR: run_dir not found: {run_dir}", file=sys.stderr)
        return 2

    # Optional wipe
    if args.wipe_derived:
        wipe_derived(run_dir)

    # Stale check
    if not args.skip_stale_check:
        ss = stale_summary(run_dir)
        if ss["stale"]:
            print(f"[stale] {run_dir.name}: {ss['reason']}")
        else:
            print(f"[fresh] {run_dir.name}: {ss['reason']}")
    else:
        ss = {"stale": None, "reason": "skip-stale-check"}

    # Resolve step scripts
    a1 = script_path(scripts_dir, "a1_make_qc_gate.py")
    a2 = script_path(scripts_dir, "a2_make_provenance_schema.py")
    a3 = script_path(scripts_dir, "a3_make_segments.py")
    a4 = script_path(scripts_dir, "a4_make_events.py")
    a5 = script_path(scripts_dir, "a5_make_run_index.py")

    missing_scripts = [str(p) for p in [a1, a2, a3, a4, a5] if not p.exists()]
    if missing_scripts:
        print("ERROR: missing step scripts:", file=sys.stderr)
        for s in missing_scripts:
            print("  -", s, file=sys.stderr)
        return 2

    # Step 1: A1 QC
    rc = run_cmd([args.python, str(a1), "--run-dir", str(run_dir)], cwd=scripts_dir, quiet=args.quiet)
    if rc != 0:
        print(f"ERROR: A1 failed (rc={rc})", file=sys.stderr)
        return rc

    qc = read_json(run_dir / "derived" / "qc_report.json")
    qc_overall = (qc or {}).get("overall")
    print(f"[A1] qc_overall={qc_overall}")

    if qc_overall == "FAIL" and not args.continue_on_fail:
        print("ERROR: QC overall is FAIL. Stop here (use --continue-on-fail to override).", file=sys.stderr)
        return 10

    # Step 2: A2 provenance/schema
    rc = run_cmd([args.python, str(a2), "--run-dir", str(run_dir)], cwd=scripts_dir, quiet=args.quiet)
    if rc != 0:
        print(f"ERROR: A2 failed (rc={rc})", file=sys.stderr)
        return rc

    # Step 3: A3 segments
    rc = run_cmd([args.python, str(a3), "--run-dir", str(run_dir)], cwd=scripts_dir, quiet=args.quiet)
    if rc != 0:
        print(f"ERROR: A3 failed (rc={rc})", file=sys.stderr)
        return rc

    # Step 4: A4 events
    rc = run_cmd([args.python, str(a4), "--run-dir", str(run_dir)], cwd=scripts_dir, quiet=args.quiet)
    if rc != 0:
        print(f"ERROR: A4 failed (rc={rc})", file=sys.stderr)
        return rc

    # Step 5: A5 runs index (whole runs_root)
    rc = run_cmd([args.python, str(a5), "--runs-root", str(runs_root)], cwd=scripts_dir, quiet=args.quiet)
    if rc != 0:
        print(f"ERROR: A5 failed (rc={rc})", file=sys.stderr)
        return rc

    # Post summary (will also embed transfer result)
    out: Dict[str, object] = {
        "run_dir": str(run_dir),
        "run_id": run_dir.name,
        "created_at": iso_now(),
        "qc_overall": qc_overall,
        "paths": {
            "qc_report_json": str(run_dir / "derived" / "qc_report.json"),
            "qc_report_md": str(run_dir / "derived" / "qc_report.md"),
            "schema_json": str(run_dir / "derived" / "schema.json"),
            "provenance_json": str(run_dir / "derived" / "provenance.json"),
            "segments_meta": str(run_dir / "derived" / "segments_meta.json"),
            "events_csv": str(run_dir / "derived" / "events.csv"),
            "runs_index_csv": str(runs_root / "derived" / "runs_index.csv"),
        },
        "stale_check": ss,
    }

    # --- Windows transfer gate (Method B: _incoming) ---
    transfer_result = None
    if args.win_incoming_dir:
        permit = (args.transfer_on_qc == "ANY") or (qc_overall == args.transfer_on_qc)
        if not permit:
            print(f"[TRANSFER SKIP] qc_overall={qc_overall} does not match transfer-on-qc={args.transfer_on_qc}")
        else:
            win_incoming_dir = Path(args.win_incoming_dir)
            win_mount_root = Path(args.win_mount_root) if args.win_mount_root else None

            tr = transfer_run_to_incoming(
                run_dir=run_dir,
                runs_root=runs_root,
                win_incoming_dir=win_incoming_dir,
                win_root_for_mount_check=win_mount_root,
                method=args.transfer_method,
                transfer_runs_index=args.transfer_runs_index,
                quiet=args.quiet,
            )
            transfer_result = tr
            print(f"[TRANSFER {tr['status']}] {tr['run_id']} -> {tr['dest_run_dir']} ({tr.get('message','')})")
            if tr.get("verify"):
                v = tr["verify"]
                print(f"[VERIFY {'OK' if v.get('ok') else 'NG'}] {v.get('msg')}")
            # marker hint
            if tr.get("status") == "OK" and (tr.get("verify") or {}).get("ok") is True:
                print(f"[INCOMING MARKER] {Path(tr['dest_run_dir']) / '_INCOMING_OK.json'}")

    if transfer_result is not None:
        out["transfer"] = transfer_result

    # Write pipeline meta marker (Pi side)
    pm = run_dir / "derived" / "pipeline_meta.json"
    try:
        with pm.open("w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    print(f"[OK] A0 pipeline complete for {run_dir.name}")
    if args.print:
        for k, v in out["paths"].items():
            print(f"{k}={v}")
        print(f"pipeline_meta={pm}")
        if transfer_result is not None:
            print(f"transfer_meta={run_dir / 'derived' / 'transfer_meta.json'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
