#!/usr/bin/env python3
"""Disambiguate MMSI matches when multiple vessels share a charter name."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from config import DATA_PROCESSED, MMSI_ALLOWLIST, MMSI_DENYLIST  # noqa: E402


def score_row(r: dict) -> float:
    mmsi = int(r["mmsi"])
    if mmsi in MMSI_DENYLIST:
        return -1e9
    if mmsi in MMSI_ALLOWLIST:
        return 1e6 + r.get("n_points", 0)
    s = 0.0
    vt = r.get("vessel_type")
    if vt in (30, 31, 60):
        s += 30
    elif vt in (36, 37):
        s -= 10
    length = r.get("length")
    if length is not None:
        if length >= 18:
            s += 20
        elif length < 12:
            s -= 15
    if r.get("call_sign"):
        s += 5
    # Prefer US mid-band MMSIs common for domestic commercial
    if str(mmsi).startswith(("366", "367", "368")):
        s += 3
    s += min(r.get("n_points", 0), 5000) / 5000.0
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
        FROM read_parquet('{glob}')
        GROUP BY mmsi
        """
    ).fetchdf()

    by_report: dict[str, list[dict]] = defaultdict(list)
    rows = []
    for _, r in stats.iterrows():
        item = {
            "mmsi": int(r["mmsi"]),
            "ais_vessel_name": r["ais_vessel_name"],
            "vessel_name_norm": r["vessel_name_norm"],
            "call_sign": None if r["call_sign"] != r["call_sign"] else r["call_sign"],
            "vessel_type": None if r["vessel_type"] != r["vessel_type"] else int(r["vessel_type"]),
            "length": None if r["length"] != r["length"] else int(r["length"]),
            "width": None if r["width"] != r["width"] else int(r["width"]),
            "report_boat_names": [r["report_boat_name"]] if r["report_boat_name"] else [],
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
