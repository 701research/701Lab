#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase B2-2a: Extract unified.csv into sensor-wise standardized parquet datasets
(temp / gps / polar) for each target run.

Input:
  work/phaseB/derived/b2/_staging/b2_1_targets.parquet
  immutable/runs/<run_id>/unified.csv

Outputs (per run):
  work/phaseB/derived/b2/runs/<run_id>/unified_temp.parquet
  work/phaseB/derived/b2/runs/<run_id>/unified_gps.parquet
  work/phaseB/derived/b2/runs/<run_id>/unified_polar_hr.parquet
  work/phaseB/derived/b2/runs/<run_id>/unified_polar_rr.parquet (if found)
  work/phaseB/derived/b2/runs/<run_id>/unified_value_catalog.json

Run:
  conda activate phaseb
  python b2_2a_extract_unified.py
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd


REQUIRED_COLS = ["seq", "t_mono", "t_wall", "source", "name", "value", "status"]


def _read_unified_csv(path: Path) -> pd.DataFrame:
    # Keep it robust: read as strings first where needed, then coerce.
    df = pd.read_csv(path, dtype={"seq": "Int64"}, low_memory=False)
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"unified.csv missing columns: {missing}")
    # Coerce numeric
    df["t_mono"] = pd.to_numeric(df["t_mono"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    # Normalize text
    for c in ["t_wall", "source", "name", "status"]:
        df[c] = df[c].astype(str)
    return df


def _catalog_source_name(df: pd.DataFrame) -> Dict[str, List[str]]:
    """
    Return mapping: source -> sorted unique names
    """
    out: Dict[str, List[str]] = {}
    for src, sub in df.groupby("source", dropna=False):
        names = sorted(set(sub["name"].astype(str).tolist()))
        out[str(src)] = names
    return out


def _find_keys(catalog: Dict[str, List[str]]) -> Dict[str, List[Tuple[str, str]]]:
    """
    Auto-detect (source,name) pairs for temp/gps/polar using substring heuristics.
    You can refine this once you see the catalog JSON.
    """
    hits: Dict[str, List[Tuple[str, str]]] = {"temp": [], "gps": [], "polar_hr": [], "polar_rr": []}

    for src, names in catalog.items():
        src_l = src.lower()

        for nm in names:
            nm_l = str(nm).lower()

            # temp
            if "temp" in src_l or src_l == "temp":
                hits["temp"].append((src, nm))

            # gps (common tokens)
            if "gps" in src_l:
                hits["gps"].append((src, nm))

            # polar
            if "polar" in src_l:
                # HR
                if nm_l in {"hr", "bpm"} or "hr" == nm_l or "heart" in nm_l:
                    hits["polar_hr"].append((src, nm))
                # RR
                if "rr" in nm_l:
                    hits["polar_rr"].append((src, nm))

            # fallback if source naming differs but name indicates sensor
            if "polar" in nm_l:
                if "hr" in nm_l:
                    hits["polar_hr"].append((src, nm))
                if "rr" in nm_l:
                    hits["polar_rr"].append((src, nm))

    # De-dup while preserving order
    def dedup(pairs: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
        seen = set()
        out2 = []
        for a, b in pairs:
            key = (a, b)
            if key not in seen:
                seen.add(key)
                out2.append(key)
        return out2

    for k in list(hits.keys()):
        hits[k] = dedup(hits[k])

    return hits


def _filter_pairs(df: pd.DataFrame, pairs: List[Tuple[str, str]]) -> pd.DataFrame:
    if not pairs:
        return df.iloc[0:0].copy()

    mask = False
    for src, nm in pairs:
        mask = mask | ((df["source"] == src) & (df["name"] == nm))
    out = df[mask].copy()
    # Standard column order
    out = out[REQUIRED_COLS].copy()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-root", default=r"D:\701lab\work")
    ap.add_argument("--also-csv", action="store_true", help="Also write CSV alongside parquet (debug)")
    ap.add_argument("--run-id", default="", help="If set, process only this run_id")
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

    out_root = work_root / "phaseB" / "derived" / "b2" / "runs"
    out_root.mkdir(parents=True, exist_ok=True)

    n_ok = 0
    n_ng = 0

    for _, t in targets.iterrows():
        run_id = str(t["run_id"])
        run_path = Path(t["run_path_immutable"])
        unified_path = run_path / "unified.csv"
        if not unified_path.exists():
            print(f"[NG] {run_id}: missing unified.csv: {unified_path}")
            n_ng += 1
            continue

        run_out = out_root / run_id
        run_out.mkdir(parents=True, exist_ok=True)

        df = _read_unified_csv(unified_path)

        catalog = _catalog_source_name(df)
        keys = _find_keys(catalog)

        # Save catalog for human inspection & mapping tweaks
        cat_out = {
            "run_id": run_id,
            "generated_at_iso_utc": datetime.now(timezone.utc).isoformat(),
            "catalog": catalog,
            "auto_keys": {k: [{"source": a, "name": b} for a, b in v] for k, v in keys.items()},
        }
        (run_out / "unified_value_catalog.json").write_text(
            json.dumps(cat_out, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Extract
        df_temp = _filter_pairs(df, keys["temp"])
        df_gps = _filter_pairs(df, keys["gps"])
        df_hr = _filter_pairs(df, keys["polar_hr"])
        df_rr = _filter_pairs(df, keys["polar_rr"])

        # Write parquet
        p_temp = run_out / "unified_temp.parquet"
        p_gps = run_out / "unified_gps.parquet"
        p_hr = run_out / "unified_polar_hr.parquet"
        p_rr = run_out / "unified_polar_rr.parquet"

        df_temp.to_parquet(p_temp, index=False)
        df_gps.to_parquet(p_gps, index=False)
        df_hr.to_parquet(p_hr, index=False)
        df_rr.to_parquet(p_rr, index=False)

        if args.also_csv:
            df_temp.to_csv(p_temp.with_suffix(".csv"), index=False, encoding="utf-8-sig")
            df_gps.to_csv(p_gps.with_suffix(".csv"), index=False, encoding="utf-8-sig")
            df_hr.to_csv(p_hr.with_suffix(".csv"), index=False, encoding="utf-8-sig")
            df_rr.to_csv(p_rr.with_suffix(".csv"), index=False, encoding="utf-8-sig")

        # Log counts
        print(f"[OK] {run_id}: temp={len(df_temp)}, gps={len(df_gps)}, polar_hr={len(df_hr)}, polar_rr={len(df_rr)}")
        n_ok += 1

    print(f"[OK] done. ok={n_ok}, ng={n_ng}")
    print(f"[OK] outputs under: {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
