#!/usr/bin/env python3
"""Disambiguate MMSI matches when multiple vessels share a charter name."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from config import DATA_PROCESSED, MMSI_ALLOWLIST, MMSI_DENYLIST  # noqa: E402


def _clean_int(val):
    if val is None or pd.isna(val):
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _clean_str(val):
    if val is None or pd.isna(val):
        return None
    s = str(val).strip()
    return s or None


def score_row(r: dict) -> float:
    mmsi = int(r["mmsi"])
    if mmsi in MMSI_DENYLIST:
        return -1e9
    if mmsi in MMSI_ALLOWLIST:
        return 1e6 + r.get("n_points", 0)

    # Auto-match guardrails: long Cadastre history surfaces many same-name
    # commercial / yacht / foreign vessels. Only keep plausible SoCal charters.
    mmsi_s = str(mmsi)
    if not mmsi_s.startswith(("366", "367", "368", "338")):
        return -1e8
    length = r.get("length")
    if length is not None and (length < 12 or length > 45):
        return -1e8

    s = 0.0
    vt = r.get("vessel_type")
    # Fishing / towing / passenger / USCG type encodings seen on charters.
    if vt in (30, 31, 60, 1001, 1012, 1019):
        s += 30
    elif vt in (36, 37):  # sailing / pleasure — weak for sportfish charters
        s -= 10
    elif vt in (70, 71, 72, 73, 74, 80, 81, 82, 83, 84, 90, 1004, 1024):
        return -1e8
    if length is not None:
        if 18 <= length <= 40:
            s += 20
        elif length < 14:
            s -= 15
    if r.get("call_sign"):
        s += 5
    if mmsi_s.startswith(("366", "367", "368")):
        s += 3
    s += min(r.get("n_points", 0), 5000) / 5000.0
    # Require a minimum auto score so weak name collisions stay rejected.
    if s < 25:
        return -1e7
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ais-dir", type=Path, default=DATA_PROCESSED / "ais_daily")
    ap.add_argument("--registry", type=Path, default=DATA_PROCESSED / "vessel_mmsi_registry.json")
    ap.add_argument("--out", type=Path, default=DATA_PROCESSED / "vessel_mmsi_registry.json")
    args = ap.parse_args()

    con = duckdb.connect()
    glob = (args.ais_dir / "ais_*.parquet").as_posix()
    stats = con.execute(
        f"""
        SELECT mmsi,
               any_value(vessel_name) AS ais_vessel_name,
               any_value(vessel_name_norm) AS vessel_name_norm,
               any_value(report_boat_name) AS report_boat_name,
               any_value(call_sign) AS call_sign,
               any_value(vessel_type) AS vessel_type,
               any_value(length) AS length,
               any_value(width) AS width,
               count(*) AS n_points,
               min(base_date_time) AS first_seen,
               max(base_date_time) AS last_seen
        FROM read_parquet('{glob}', union_by_name=true)
        GROUP BY mmsi
        """
    ).fetchdf()

    by_report: dict[str, list[dict]] = defaultdict(list)
    rows = []
    for _, r in stats.iterrows():
        report_name = _clean_str(r["report_boat_name"])
        item = {
            "mmsi": int(r["mmsi"]),
            "ais_vessel_name": _clean_str(r["ais_vessel_name"]),
            "vessel_name_norm": _clean_str(r["vessel_name_norm"]),
            "call_sign": _clean_str(r["call_sign"]),
            "vessel_type": _clean_int(r["vessel_type"]),
            "length": _clean_int(r["length"]),
            "width": _clean_int(r["width"]),
            "report_boat_names": [report_name] if report_name else [],
            "n_points": int(r["n_points"]),
            "first_seen": str(r["first_seen"]),
            "last_seen": str(r["last_seen"]),
        }
        item["score"] = score_row(item)
        rows.append(item)
        if item["report_boat_names"]:
            by_report[item["report_boat_names"][0]].append(item)

    selected_mmsis: set[int] = set()
    rejected = []
    for boat, items in by_report.items():
        items_sorted = sorted(items, key=lambda x: x["score"], reverse=True)
        best = items_sorted[0]
        if best["score"] < 0:
            for it in items_sorted:
                it["match_confidence"] = "rejected"
                rejected.append(it)
            continue
        best["match_confidence"] = "high"
        selected_mmsis.add(best["mmsi"])
        # Keep additional MMSIs only if also allowlisted and score competitive
        for it in items_sorted[1:]:
            if it["mmsi"] in MMSI_ALLOWLIST and it["score"] > 0:
                it["match_confidence"] = "high_secondary"
                selected_mmsis.add(it["mmsi"])
            else:
                it["match_confidence"] = "rejected_duplicate_name"
                rejected.append(it)

    final = [r for r in rows if r["mmsi"] in selected_mmsis]
    for r in final:
        r.setdefault("match_confidence", "high")

    args.out.write_text(json.dumps(final, indent=2))
    debug_path = DATA_PROCESSED / "mmsi_rejected.json"
    debug_path.write_text(json.dumps(rejected, indent=2))
    print(f"Selected {len(final)} MMSIs -> {args.out}")
    print(f"Rejected {len(rejected)} -> {debug_path}")
    for r in sorted(final, key=lambda x: -x["n_points"]):
        print(
            f"{r['mmsi']} {r['ais_vessel_name']!r:22} -> {r['report_boat_names']} "
            f"type={r['vessel_type']} len={r['length']} score={r['score']:.1f}"
        )


if __name__ == "__main__":
    main()
