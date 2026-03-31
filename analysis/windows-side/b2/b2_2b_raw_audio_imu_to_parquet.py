#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase B2-2b:
- audio.wav: health check only (duration/rms/peak/clip ratio)
- imu_bwt901cl.bin: restore 31B records (frame11 + meta20) with auto hypothesis detection,
  then write frame-wise parquet: imu_accel / imu_gyro / imu_angle / imu_mag

Inputs:
  work/phaseB/derived/b2/_staging/b2_1_targets.parquet
  immutable/runs/<run_id>/raw/audio.wav
  immutable/runs/<run_id>/raw/imu_bwt901cl.bin

Outputs (per run):
  work/phaseB/derived/b2/runs/<run_id>/raw_audio_health.json
  work/phaseB/derived/b2/runs/<run_id>/imu_accel.parquet
  work/phaseB/derived/b2/runs/<run_id>/imu_gyro.parquet
  work/phaseB/derived/b2/runs/<run_id>/imu_angle.parquet
  work/phaseB/derived/b2/runs/<run_id>/imu_mag.parquet
  work/phaseB/derived/b2/runs/<run_id>/imu_restore_meta.json

Output (cross-run):
  work/phaseB/derived/b2/_staging/b2_2b_raw_summary.parquet

Run:
  conda activate phaseb
  python b2_2b_raw_audio_imu_to_parquet.py
  python b2_2b_raw_audio_imu_to_parquet.py --force
  python b2_2b_raw_audio_imu_to_parquet.py --run-id run_....
"""

from __future__ import annotations

import argparse
import json
import math
import mmap
import wave
import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from collections import Counter

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


# ---------------- WITMOTION decode ----------------

def _i16(lo: int, hi: int) -> int:
    v = (hi << 8) | lo
    return v - 65536 if v >= 32768 else v

def checksum_ok(frame: bytes) -> bool:
    return len(frame) == 11 and ((sum(frame[:10]) & 0xFF) == frame[10])

def decode_frame(frame: bytes) -> Tuple[bool, Optional[int], Dict[str, Any]]:
    out: Dict[str, Any] = {}
    if len(frame) != 11 or frame[0] != 0x55:
        out["err"] = "bad_frame_len_or_sync"
        return False, None, out

    fid = frame[1]
    out["frame_id"] = fid

    if not checksum_ok(frame):
        out["err"] = "bad_checksum"
        return False, fid, out

    d = frame[2:10]
    x = _i16(d[0], d[1])
    y = _i16(d[2], d[3])
    z = _i16(d[4], d[5])
    t_raw = _i16(d[6], d[7])
    out["temp_raw"] = t_raw

    if fid == 0x51:
        out["ax_g"] = x / 32768.0 * 16.0
        out["ay_g"] = y / 32768.0 * 16.0
        out["az_g"] = z / 32768.0 * 16.0
        return True, fid, out
    if fid == 0x52:
        out["gx_dps"] = x / 32768.0 * 2000.0
        out["gy_dps"] = y / 32768.0 * 2000.0
        out["gz_dps"] = z / 32768.0 * 2000.0
        return True, fid, out
    if fid == 0x53:
        out["roll_deg"] = x / 32768.0 * 180.0
        out["pitch_deg"] = y / 32768.0 * 180.0
        out["yaw_deg"] = z / 32768.0 * 180.0
        return True, fid, out
    if fid == 0x54:
        out["mx_raw"] = x
        out["my_raw"] = y
        out["mz_raw"] = z
        return True, fid, out

    out["err"] = "unsupported_fid"
    return False, fid, out

def fid_name(fid: Optional[int]) -> str:
    if fid is None:
        return ""
    return {0x51: "accel", 0x52: "gyro", 0x53: "angle", 0x54: "mag"}.get(fid, f"0x{fid:02X}")

def wall_iso_local_from_ms(ms: int) -> str:
    sec = ms / 1000.0
    d = dt.datetime.fromtimestamp(sec)
    return d.isoformat(timespec="milliseconds")


# ---------------- record/meta layout detection ----------------

@dataclass(frozen=True)
class Hypothesis:
    meta_pos: str        # "before" or "after"
    field_order: str     # "mono_wall_seq" or "wall_mono_seq"
    endian: str          # "little" or "big"

def _u64(b: bytes, endian: str) -> int:
    return int.from_bytes(b, endian, signed=False)

def _u32(b: bytes, endian: str) -> int:
    return int.from_bytes(b, endian, signed=False)

def parse_meta20(meta20: bytes, hyp: Hypothesis) -> Tuple[int, int, int]:
    if len(meta20) != 20:
        raise ValueError("meta20_len")
    a = _u64(meta20[0:8], hyp.endian)
    b = _u64(meta20[8:16], hyp.endian)
    c = _u32(meta20[16:20], hyp.endian)
    if hyp.field_order == "mono_wall_seq":
        return a, b, c
    else:
        return b, a, c

def score_series(mono_ns: List[int], wall_ms: List[int], seqs: List[int]) -> float:
    if len(mono_ns) < 50:
        return -1e18

    def in_range(x: int, lo: int, hi: int) -> bool:
        return lo <= x <= hi

    score = 0.0
    mono_good = sum(1 for x in mono_ns if in_range(x, 10**9, 10**16))
    wall_good = sum(1 for x in wall_ms if in_range(x, 10**11, 10**13))
    score += 2.0 * mono_good + 2.0 * wall_good

    mono_inc = sum(1 for i in range(1, len(mono_ns)) if mono_ns[i] > mono_ns[i-1])
    wall_inc = sum(1 for i in range(1, len(wall_ms)) if wall_ms[i] >= wall_ms[i-1])
    score += 5.0 * mono_inc + 5.0 * wall_inc

    mono_d = [mono_ns[i]-mono_ns[i-1] for i in range(1, len(mono_ns)) if mono_ns[i] > mono_ns[i-1]]
    wall_d = [wall_ms[i]-wall_ms[i-1] for i in range(1, len(wall_ms)) if wall_ms[i] >= wall_ms[i-1]]

    if mono_d:
        mono_step_good = sum(1 for d in mono_d if 10**6 <= d <= 10**9)
        score += 1.0 * mono_step_good
    if wall_d:
        wall_step_good = sum(1 for d in wall_d if 0 <= d <= 5000)
        score += 1.0 * wall_step_good

    if seqs:
        seq_inc = sum(1 for i in range(1, len(seqs)) if seqs[i] >= seqs[i-1])
        score += 0.5 * seq_inc

    return score

def find_valid_frame_positions_mm(mm: mmap.mmap, max_hits: int = 10_000_000) -> List[int]:
    """
    Scan for valid checksum frames.
    Uses mmap for large files.
    """
    pos: List[int] = []
    n = mm.size()
    i = 0
    # Simple scan; adequate for typical file sizes.
    while i + 11 <= n:
        if mm[i] != 0x55:
            i += 1
            continue
        fr = mm[i:i+11]
        if checksum_ok(fr):
            pos.append(i)
            if len(pos) >= max_hits:
                break
        i += 1
    return pos

def detect_stride(positions: List[int]) -> int:
    if len(positions) < 20:
        return 0
    d = [positions[i+1] - positions[i] for i in range(len(positions)-1)]
    c = Counter(d)
    stride, _ = c.most_common(1)[0]
    return stride

def choose_best_hypothesis_mm(mm: mmap.mmap, positions: List[int], max_eval: int = 800) -> Tuple[Hypothesis, float]:
    positions = positions[:max_eval]

    hyps: List[Hypothesis] = []
    for meta_pos in ("before", "after"):
        for field_order in ("mono_wall_seq", "wall_mono_seq"):
            for endian in ("little", "big"):
                hyps.append(Hypothesis(meta_pos, field_order, endian))

    best = hyps[0]
    best_score = -1e18

    for hyp in hyps:
        mono_ns: List[int] = []
        wall_ms: List[int] = []
        seqs: List[int] = []

        for p in positions:
            try:
                if hyp.meta_pos == "after":
                    rec = mm[p:p+31]
                    if len(rec) < 31:
                        continue
                    frame = rec[0:11]
                    meta20 = rec[11:31]
                else:
                    if p < 20:
                        continue
                    meta20 = mm[p-20:p]
                    frame = mm[p:p+11]
                    if len(frame) < 11 or len(meta20) < 20:
                        continue

                if not checksum_ok(frame):
                    continue

                mn, wm, sq = parse_meta20(meta20, hyp)
                mono_ns.append(mn)
                wall_ms.append(wm)
                seqs.append(sq)
            except Exception:
                continue

        sc = score_series(mono_ns, wall_ms, seqs)
        if sc > best_score:
            best_score = sc
            best = hyp

    return best, best_score


# ---------------- parquet writers (chunked) ----------------

def _make_writer(path: Path, schema: pa.Schema) -> pq.ParquetWriter:
    path.parent.mkdir(parents=True, exist_ok=True)
    return pq.ParquetWriter(str(path), schema=schema, compression="snappy", use_dictionary=True)

def _write_chunk(writer: Optional[pq.ParquetWriter], path: Path, rows: List[Dict[str, Any]]) -> pq.ParquetWriter:
    df = pd.DataFrame(rows)
    # Ensure stable dtypes where possible
    table = pa.Table.from_pandas(df, preserve_index=False)
    if writer is None:
        writer = _make_writer(path, table.schema)
    writer.write_table(table)
    return writer


# ---------------- audio health ----------------

def audio_health(wav_path: Path, chunk_frames: int = 65536) -> Dict[str, Any]:
    """
    Minimal health for sync usage:
    - duration
    - rms (overall)
    - peak
    - clip_ratio (|x| >= 0.98*max_int16)
    """
    out: Dict[str, Any] = {
        "path": str(wav_path),
        "ok": False,
        "error": "",
    }

    try:
        with wave.open(str(wav_path), "rb") as w:
            ch = w.getnchannels()
            sr = w.getframerate()
            sw = w.getsampwidth()
            n = w.getnframes()

            out["channels"] = ch
            out["sample_rate_hz"] = sr
            out["sample_width_bytes"] = sw
            out["n_frames"] = n
            out["duration_s"] = float(n) / float(sr) if sr else None

            if sw != 2:
                out["error"] = f"unsupported sample width: {sw} (expected 2 bytes int16)"
                return out

            max_i16 = 32767
            clip_thr = int(0.98 * max_i16)

            sumsq = 0.0
            peak = 0
            clip = 0
            total = 0

            while True:
                raw = w.readframes(chunk_frames)
                if not raw:
                    break
                # int16 little-endian
                # convert manually without numpy (keep deps minimal)
                # raw length multiple of 2
                m = len(raw) // 2
                total += m
                for i in range(0, len(raw), 2):
                    v = int.from_bytes(raw[i:i+2], "little", signed=True)
                    av = abs(v)
                    if av > peak:
                        peak = av
                    if av >= clip_thr:
                        clip += 1
                    sumsq += float(v) * float(v)

            out["peak_abs_i16"] = int(peak)
            out["rms_i16"] = math.sqrt(sumsq / total) if total else None
            out["clip_ratio"] = float(clip) / float(total) if total else None
            out["ok"] = True
            return out

    except Exception as e:
        out["error"] = str(e)
        return out


# ---------------- main pipeline ----------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-root", default=r"D:\701lab\work")
    ap.add_argument("--run-id", default="", help="Process only one run_id")
    ap.add_argument("--force", action="store_true", help="Overwrite outputs if exist")
    ap.add_argument("--imu-chunk", type=int, default=200_000, help="Rows per chunk write (per frame type)")
    args = ap.parse_args()

    work_root = Path(args.work_root)
    targets_path = work_root / "phaseB" / "derived" / "b2" / "_staging" / "b2_1_targets.parquet"
    if not targets_path.exists():
        raise SystemExit(f"[NG] targets not found: {targets_path}")

    targets = pd.read_parquet(targets_path)
    if args.run_id:
        targets = targets[targets["run_id"] == args.run_id].copy()

    if len(targets) == 0:
        print("[WARN] no targets to process")
        return 0

    out_runs = work_root / "phaseB" / "derived" / "b2" / "runs"
    out_runs.mkdir(parents=True, exist_ok=True)

    summary_rows: List[Dict[str, Any]] = []

    for _, t in targets.iterrows():
        run_id = str(t["run_id"])
        run_path = Path(t["run_path_immutable"])
        raw_dir = run_path / "raw"
        audio_path = raw_dir / "audio.wav"
        imu_path = raw_dir / "imu_bwt901cl.bin"

        run_out = out_runs / run_id
        run_out.mkdir(parents=True, exist_ok=True)

        # ---------- audio health ----------
        audio_out = run_out / "raw_audio_health.json"
        if audio_path.exists() and (args.force or not audio_out.exists()):
            ah = audio_health(audio_path)
            ah["generated_at_iso_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
            audio_out.write_text(json.dumps(ah, ensure_ascii=False, indent=2), encoding="utf-8")
        elif not audio_path.exists():
            # still record
            audio_out.write_text(json.dumps({
                "path": str(audio_path),
                "ok": False,
                "error": "missing",
                "generated_at_iso_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            }, ensure_ascii=False, indent=2), encoding="utf-8")

        # ---------- IMU restore ----------
        imu_meta_out = run_out / "imu_restore_meta.json"
        p_acc = run_out / "imu_accel.parquet"
        p_gyr = run_out / "imu_gyro.parquet"
        p_ang = run_out / "imu_angle.parquet"
        p_mag = run_out / "imu_mag.parquet"

        if (not imu_path.exists()):
            print(f"[WARN] {run_id}: missing imu bin: {imu_path}")
            summary_rows.append({
                "run_id": run_id,
                "imu_ok": False,
                "imu_error": "missing_bin",
                "audio_path": str(audio_path),
                "imu_path": str(imu_path),
            })
            continue

        if (not args.force) and p_acc.exists() and p_gyr.exists() and p_ang.exists() and p_mag.exists():
            print(f"[OK] {run_id}: IMU parquet exists (skip). use --force to rebuild.")
            summary_rows.append({
                "run_id": run_id,
                "imu_ok": True,
                "imu_error": "",
                "accel_rows": None,
                "gyro_rows": None,
                "angle_rows": None,
                "mag_rows": None,
                "audio_path": str(audio_path),
                "imu_path": str(imu_path),
                "note": "skipped_existing",
            })
            continue

        # restore using mmap
        with imu_path.open("rb") as f:
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)

            # find valid frames
            positions = find_valid_frame_positions_mm(mm, max_hits=10_000_000)
            if not positions:
                mm.close()
                print(f"[NG] {run_id}: no valid WITMOTION frames found (checksum_ok)")
                summary_rows.append({
                    "run_id": run_id,
                    "imu_ok": False,
                    "imu_error": "no_valid_frames",
                    "audio_path": str(audio_path),
                    "imu_path": str(imu_path),
                })
                continue

            stride = detect_stride(positions)
            hyp, sc = choose_best_hypothesis_mm(mm, positions, max_eval=800)

            imu_meta = {
                "run_id": run_id,
                "generated_at_iso_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "imu_path": str(imu_path),
                "file_size_bytes": int(mm.size()),
                "valid_frames": int(len(positions)),
                "stride_mode": int(stride),
                "best_hypothesis": {"meta_pos": hyp.meta_pos, "field_order": hyp.field_order, "endian": hyp.endian},
                "score": float(sc),
            }
            imu_meta_out.write_text(json.dumps(imu_meta, ensure_ascii=False, indent=2), encoding="utf-8")

            # writers per frame
            w_acc = None
            w_gyr = None
            w_ang = None
            w_mag = None

            rows_acc: List[Dict[str, Any]] = []
            rows_gyr: List[Dict[str, Any]] = []
            rows_ang: List[Dict[str, Any]] = []
            rows_mag: List[Dict[str, Any]] = []

            n_acc = n_gyr = n_ang = n_mag = 0
            wrote = 0

            for p in positions:
                try:
                    if hyp.meta_pos == "after":
                        rec = mm[p:p+31]
                        if len(rec) < 31:
                            continue
                        frame = rec[0:11]
                        meta20 = rec[11:31]
                    else:
                        if p < 20:
                            continue
                        meta20 = mm[p-20:p]
                        frame = mm[p:p+11]
                        if len(frame) < 11 or len(meta20) < 20:
                            continue

                    ok, fid, vals = decode_frame(frame)
                    if not ok:
                        continue

                    mono_ns, wall_ms, seq_u32 = parse_meta20(meta20, hyp)
                    t_mono_s = mono_ns / 1e9
                    try:
                        t_wall = wall_iso_local_from_ms(int(wall_ms))
                    except Exception:
                        t_wall = ""

                    base = {
                        "idx_frame": int(p),
                        "t_mono_ns": int(mono_ns),
                        "t_mono_s": float(t_mono_s),
                        "t_wall_ms": int(wall_ms),
                        "t_wall": str(t_wall),
                        "seq_meta_u32": int(seq_u32),
                        "temp_raw": int(vals.get("temp_raw", 0)),
                    }

                    if fid == 0x51:
                        row = dict(base)
                        row.update({
                            "ax_g": float(vals.get("ax_g", float("nan"))),
                            "ay_g": float(vals.get("ay_g", float("nan"))),
                            "az_g": float(vals.get("az_g", float("nan"))),
                        })
                        rows_acc.append(row)
                        n_acc += 1
                        if len(rows_acc) >= args.imu_chunk:
                            w_acc = _write_chunk(w_acc, p_acc, rows_acc)
                            wrote += len(rows_acc)
                            rows_acc.clear()

                    elif fid == 0x52:
                        row = dict(base)
                        row.update({
                            "gx_dps": float(vals.get("gx_dps", float("nan"))),
                            "gy_dps": float(vals.get("gy_dps", float("nan"))),
                            "gz_dps": float(vals.get("gz_dps", float("nan"))),
                        })
                        rows_gyr.append(row)
                        n_gyr += 1
                        if len(rows_gyr) >= args.imu_chunk:
                            w_gyr = _write_chunk(w_gyr, p_gyr, rows_gyr)
                            wrote += len(rows_gyr)
                            rows_gyr.clear()

                    elif fid == 0x53:
                        row = dict(base)
                        row.update({
                            "roll_deg": float(vals.get("roll_deg", float("nan"))),
                            "pitch_deg": float(vals.get("pitch_deg", float("nan"))),
                            "yaw_deg": float(vals.get("yaw_deg", float("nan"))),
                        })
                        rows_ang.append(row)
                        n_ang += 1
                        if len(rows_ang) >= args.imu_chunk:
                            w_ang = _write_chunk(w_ang, p_ang, rows_ang)
                            wrote += len(rows_ang)
                            rows_ang.clear()

                    elif fid == 0x54:
                        row = dict(base)
                        row.update({
                            "mx_raw": int(vals.get("mx_raw", 0)),
                            "my_raw": int(vals.get("my_raw", 0)),
                            "mz_raw": int(vals.get("mz_raw", 0)),
                        })
                        rows_mag.append(row)
                        n_mag += 1
                        if len(rows_mag) >= args.imu_chunk:
                            w_mag = _write_chunk(w_mag, p_mag, rows_mag)
                            wrote += len(rows_mag)
                            rows_mag.clear()

                except Exception:
                    continue

            # flush remaining
            if rows_acc:
                w_acc = _write_chunk(w_acc, p_acc, rows_acc); wrote += len(rows_acc); rows_acc.clear()
            if rows_gyr:
                w_gyr = _write_chunk(w_gyr, p_gyr, rows_gyr); wrote += len(rows_gyr); rows_gyr.clear()
            if rows_ang:
                w_ang = _write_chunk(w_ang, p_ang, rows_ang); wrote += len(rows_ang); rows_ang.clear()
            if rows_mag:
                w_mag = _write_chunk(w_mag, p_mag, rows_mag); wrote += len(rows_mag); rows_mag.clear()

            # close writers
            for w in (w_acc, w_gyr, w_ang, w_mag):
                if w is not None:
                    w.close()

            mm.close()

        print(f"[OK] {run_id}: imu accel={n_acc}, gyro={n_gyr}, angle={n_ang}, mag={n_mag}")
        summary_rows.append({
            "run_id": run_id,
            "imu_ok": True,
            "imu_error": "",
            "accel_rows": int(n_acc),
            "gyro_rows": int(n_gyr),
            "angle_rows": int(n_ang),
            "mag_rows": int(n_mag),
            "audio_path": str(audio_path),
            "imu_path": str(imu_path),
            "imu_best_meta_pos": hyp.meta_pos,
            "imu_best_field_order": hyp.field_order,
            "imu_best_endian": hyp.endian,
            "imu_score": float(sc),
        })

    # cross-run summary
    out_staging = work_root / "phaseB" / "derived" / "b2" / "_staging"
    out_staging.mkdir(parents=True, exist_ok=True)
    sum_df = pd.DataFrame(summary_rows)
    sum_path = out_staging / "b2_2b_raw_summary.parquet"
    sum_df.to_parquet(sum_path, index=False)

    print(f"[OK] wrote: {sum_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
