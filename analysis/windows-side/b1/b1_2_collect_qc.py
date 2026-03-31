#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase B1-2: Collect QC summary for each run (lightweight, current layout)

Input:
  work\phaseB\derived\b1\_staging\b1_1_runs_base.parquet

Reads (per run):
  immutable\runs\run_*\derived\qc_report.json (preferred)
  immutable\runs\run_*\derived\qc_report.md   (fallback)

Output:
  work\phaseB\derived\b1\_staging\b1_2_runs_with_qc.parquet
  (+ optional CSV)

Run:
  conda activate phaseb
  python b1_2_collect_qc.py --also-csv
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


def _safe_read_json(p: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _normalize_overall(x: Optional[str]) -> str:
    if not x:
        return "UNKNOWN"
    s = str(x).strip().upper()
    if s in {"OK", "WARN", "FAIL"}:
        return s
    if "WARN" in s:
        return "WARN"
    if "FAIL" in s or "ERROR" in s:
        return "FAIL"
    if "OK" in s or "PASS" in s:
        return "OK"
    return "UNKNOWN"


def _collect_reason_strings(obj: Any) -> List[str]:
    """
    Extract "reason-like" strings from nested json structures in a tolerant way.
    """
    reasons: List[str] = []

    if obj is None:
        return reasons

    if isinstance(obj, str):
        s = obj.strip()
        if s:
            reasons.append(s)
        return reasons

    if isinstance(obj, dict):
        # common fields
        for k in ["reason", "reasons", "flag", "flags", "name", "message", "messages", "warning", "warnings", "error", "errors", "notes"]:
            if k in obj:
                reasons.extend(_collect_reason_strings(obj[k]))

        # dict-of-bools pattern: {"gps_no_fix": true}
        for k, v in obj.items():
            if isinstance(v, bool) and v is True:
                reasons.append(str(k))
        return reasons

    if isinstance(obj, list):
        for item in obj:
            reasons.extend(_collect_reason_strings(item))
        return reasons

    return reasons


def _parse_qc_report_json(qc: Dict[str, Any]) -> Tuple[str, List[str]]:
    # try common overall fields
    overall = (
        qc.get("qc_overall")
        or qc.get("overall")
        or qc.get("status")
        or qc.get("result")
    )
    overall_norm = _normalize_overall(overall)

    # reasons: try a few likely containers, then fall back to whole doc scan
    reasons: List[str] = []
    for k in ["reasons", "flags", "warnings", "errors", "checks", "summary", "details"]:
        if k in qc:
            reasons.extend(_collect_reason_strings(qc[k]))

    if not reasons:
        # last resort: scan whole doc but keep it short
        reasons.extend(_collect_reason_strings(qc))

    # clean & de-dup
    cleaned: List[str] = []
    seen = set()
    for r in reasons:
        s = str(r).strip()
        if not s:
            continue
        # keep manageable items only
        if len(s) > 200:
            continue
        if s not in seen:
            seen.add(s)
            cleaned.append(s)
    return overall_norm, cleaned


QC_OVERALL_RE = re.compile(r"\bqc_overall\s*=\s*(OK|WARN|FAIL)\b", re.IGNORECASE)


def _parse_qc_report_md(text: str) -> Tuple[str, List[str]]:
    overall = "UNKNOWN"
    m = QC_OVERALL_RE.search(text)
    if m:
        overall = _normalize_overall(m.group(1))

    reasons: List[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if re.search(r"\b(WARN|FAIL)\b", s, re.IGNORECASE) and len(s) <= 160:
            reasons.append(s.lstrip("-* ").strip())

    # de-dup
    out: List[str] = []
    seen = set()
    for r in reasons:
        if r and r not in seen:
            seen.add(r)
            out.append(r)
    return overall, out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-root", default=r"D:\701lab\work")
    ap.add_argument("--in-parquet", default="")
    ap.add_argument("--out-parquet", default="")
    ap.add_argument("--also-csv", action="store_true")
    args = ap.parse_args()

    work_root = Path(args.work_root)
    staging = work_root / "phaseB" / "derived" / "b1" / "_staging"
    in_parquet = Path(args.in_parquet) if args.in_parquet else (staging / "b1_1_runs_base.parquet")
    out_parquet = Path(args.out_parquet) if args.out_parquet else (staging / "b1_2_runs_with_qc.parquet")
    out_parquet.parent.mkdir(parents=True, exist_ok=True)

    if not in_parquet.exists():
        raise SystemExit(f"[NG] input not found: {in_parquet}")

    df = pd.read_parquet(in_parquet)

    qc_overall_list: List[str] = []
    qc_reasons_list: List[str] = []
    qc_source_list: List[str] = []
    qc_error_list: List[Optional[str]] = []

    now_iso = datetime.now(timezone.utc).isoformat()

    for _, row in df.iterrows():
        run_path = Path(row["run_path_immutable"])
        qc_json_path = run_path / "derived" / "qc_report.json"
        qc_md_path = run_path / "derived" / "qc_report.md"

        overall = "UNKNOWN"
        reasons: List[str] = []
        src = "NONE"
        err: Optional[str] = None

        if qc_json_path.exists():
            qc, e = _safe_read_json(qc_json_path)
            if qc is None:
                src = "derived/qc_report.json"
                err = e
            else:
                overall, reasons = _parse_qc_report_json(qc)
                src = "derived/qc_report.json"

        elif qc_md_path.exists():
            try:
                text = qc_md_path.read_text(encoding="utf-8", errors="replace")
                overall, reasons = _parse_qc_report_md(text)
                src = "derived/qc_report.md"
            except Exception as e:
                src = "derived/qc_report.md"
                err = f"{type(e).__name__}: {e}"

        qc_overall_list.append(overall)
        qc_reasons_list.append(";".join(reasons))  # CSV-safe
        qc_source_list.append(src)
        qc_error_list.append(err)

    out = df.copy()
    out["qc_overall"] = qc_overall_list
    out["qc_reasons"] = qc_reasons_list
    out["qc_source"] = qc_source_list
    out["qc_error"] = qc_error_list
    out["b1_2_ingested_at_iso_utc"] = now_iso

    out.to_parquet(out_parquet, index=False)
    if args.also_csv:
        out_csv = out_parquet.with_suffix(".csv")
        out.to_csv(out_csv, index=False, encoding="utf-8-sig")

    print(f"[OK] input : {in_parquet}")
    print(f"[OK] wrote : {out_parquet}")
    if args.also_csv:
        print(f"[OK] wrote : {out_csv}")

    print("[INFO] qc_overall counts:")
    print(out["qc_overall"].value_counts(dropna=False).to_string())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
