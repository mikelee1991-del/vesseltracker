#!/usr/bin/env python3
"""
Join fish-report trip stats with AIS offshore stops and export GitHub Pages JSON.

Catch attribution rule (per product decision): do NOT split day totals across
stops. Trip-level fish/person is authoritative; stops are location/time context
only. Location productivity estimates are deferred / clearly labeled later.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from config import (  # noqa: E402
    DATA_PROCESSED,
    DATA_RAW,
    DOCS_DATA,
    FISH_REPORT_SOURCE,
    HOME_DOCKS,
    PILOT_AIS_END,
    PILOT_AIS_START,
    PILOT_REPORT_END,
    PILOT_REPORT_START,
    TARGET_CITIES,
    VESSEL_ALIASES,
)
from extract_ais import build_accepted_names, normalize_name  # noqa: E402


def load_trips(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    with path.open() as f:
        for line in f:
            rows.append(json.loads(line))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trips", type=Path, default=DATA_RAW / "fish_reports" / "trips.jsonl")
    ap.add_argument("--stops", type=Path, default=DATA_PROCESSED / "offshore_stops.json")
    ap.add_argument("--registry", type=Path, default=DATA_PROCESSED / "vessel_mmsi_registry.json")
    ap.add_argument("--out-dir", type=Path, default=DOCS_DATA)
    args = ap.parse_args()

    trips = load_trips(args.trips)
    stops = json.loads(args.stops.read_text()) if args.stops.exists() else []
    registry = json.loads(args.registry.read_text()) if args.registry.exists() else []
    accepted = build_accepted_names(args.trips)

    # Map report boat name -> mmsi(s) using registry high-confidence rows only.
    name_to_mmsi: dict[str, set[int]] = defaultdict(set)
    for r in registry:
        if r.get("match_confidence") != "high":
            continue
        mmsi = int(r["mmsi"])
        for bn in r.get("report_boat_names") or []:
            name_to_mmsi[normalize_name(bn)].add(mmsi)
        ais_norm = normalize_name(r.get("ais_vessel_name", ""))
        if ais_norm in accepted:
            name_to_mmsi[normalize_name(accepted[ais_norm])].add(mmsi)

    # Index stops by mmsi + local date (UTC date; documented limitation)
    stops_by_key: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for s in stops:
        stops_by_key[(int(s["mmsi"]), s["date"][:10])].append(
            {
                "lat": s["lat"],
                "lon": s["lon"],
                "duration_min": s["duration_min"],
                "start_utc": s["start_utc"],
                "end_utc": s["end_utc"],
                "grid_id": s["grid_id"],
                "ais_vessel_name": s["ais_vessel_name"],
                "mean_sog_kn": s["mean_sog_kn"],
                "n_points": s["n_points"],
            }
        )

    # Filter trips to AIS pilot window for map primary layer (still export all
    # report dates for day slider coverage of report-only days).
    by_date: dict[str, list[dict]] = defaultdict(list)
    unmatched_trips = 0
    matched_with_stops = 0
    for t in trips:
        key = normalize_name(t["boat_name"])
        mmsis = set(name_to_mmsi.get(key, set()))
        trip_stops = []
        for m in sorted(mmsis):
            trip_stops.extend(stops_by_key.get((m, t["date"]), []))
        if mmsis and trip_stops:
            matched_with_stops += 1
        elif not mmsis:
            unmatched_trips += 1

        species_pp = t.get("species_per_person") or {}
        # Keep only kept fish in species list for display.
        kept_species = [
            {"species": s["species"], "count": s["count"], "per_person": species_pp.get(s["species"])}
            for s in t.get("species", [])
            if not s.get("released")
        ]
        by_date[t["date"]].append(
            {
                "date": t["date"],
                "boat_name": t["boat_name"],
                "city": t["city"],
                "landing_name": t["landing_name"],
                "anglers": t["anglers"],
                "trip_type": t["trip_type"],
                "total_fish_kept": t["total_fish_kept"],
                "fish_per_person": t["fish_per_person"],
                "species": kept_species,
                "mmsis": sorted(mmsis),
                "offshore_stops": trip_stops,
                "catch_attribution": "trip_total_not_split_across_stops",
                "source": t.get("source"),
            }
        )

    dates = sorted(by_date.keys())
    days_out = []
    for d in dates:
        trips_d = by_date[d]
        fpp_vals = [x["fish_per_person"] for x in trips_d if x["fish_per_person"] is not None]
        days_out.append(
            {
                "date": d,
                "n_trips": len(trips_d),
                "mean_fish_per_person": (sum(fpp_vals) / len(fpp_vals)) if fpp_vals else None,
                "trips": trips_d,
            }
        )

    # Compact per-day files + index for scalable loading.
    args.out_dir.mkdir(parents=True, exist_ok=True)
    days_dir = args.out_dir / "days"
    days_dir.mkdir(exist_ok=True)
    for day in days_out:
        (days_dir / f"{day['date']}.json").write_text(json.dumps(day))

    meta = {
        "title": "LA-area sportfishing take (pilot)",
        "description": (
            "Fish-per-person from socalfishreports.com dock totals, joined to "
            "Marine Cadastre AIS offshore stops. Catch counts are NOT split "
            "across stop locations."
        ),
        "sources": {
            "fish_reports": FISH_REPORT_SOURCE,
            "ais": "NOAA Marine Cadastre / U.S. Coast Guard NAIS daily CSV (1-minute sample)",
            "bathymetry": "NOAA BlueTopo via nowCOAST WMTS",
        },
        "target_cities": sorted(TARGET_CITIES),
        "report_window": {"start": PILOT_REPORT_START, "end": PILOT_REPORT_END},
        "ais_window": {"start": PILOT_AIS_START, "end": PILOT_AIS_END},
        "ais_availability_note": (
            "As of 2026-08-02, free Marine Cadastre bulk AIS daily files for this "
            "pipeline were available through 2025-12-31. 2026 AIS is not yet in "
            "the bulk feed used here."
        ),
        "methods": {
            "fish_per_person": "total kept fish / anglers from the dock total (direct)",
            "species_per_person": "species kept count / anglers (direct)",
            "offshore_stops": (
                f"SOG <= configured max, duration >= configured min, outside home-dock radii; "
                f"see scripts/config.py"
            ),
            "catch_location_attribution": (
                "NOT applied. Trip totals remain at voyage level. Location "
                "productivity will be estimated later by cross-vessel statistics."
            ),
        },
        "home_docks": HOME_DOCKS,
        "dates": dates,
        "stats": {
            "n_days_with_reports": len(dates),
            "n_trips": len(trips),
            "n_offshore_stops": len(stops),
            "n_registry_vessels": len(registry),
            "n_trips_with_stops_in_ais_window": matched_with_stops,
            "n_trips_unmatched_to_mmsi": unmatched_trips,
        },
        "default_date": next((d for d in reversed(dates) if PILOT_AIS_START <= d <= PILOT_AIS_END), dates[-1] if dates else None),
    }
    (args.out_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    # Also a small debug summary for FEEDBACK loop.
    debug = {
        "unmatched_boat_names": sorted(
            {t["boat_name"] for t in trips if not name_to_mmsi.get(normalize_name(t["boat_name"]))}
        ),
        "accepted_ais_name_keys": sorted(accepted.keys()),
        "vessel_aliases_config": VESSEL_ALIASES,
        "registry_non_high": [r for r in registry if r.get("match_confidence") != "high"],
        "notes": [
            "Edit FEEDBACK.md / scripts/config.py VESSEL_ALIASES to correct MMSI/boat matches.",
            "UTC date used for AIS-to-report day join (Pacific local day shift possible).",
        ],
    }
    (DATA_PROCESSED / "join_debug.json").write_text(json.dumps(debug, indent=2))
    print(json.dumps(meta["stats"], indent=2))
    print(f"Wrote map data -> {args.out_dir}")


if __name__ == "__main__":
    main()
