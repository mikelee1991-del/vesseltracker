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
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
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


def detect_ais_window(ais_dir: Path) -> tuple[str | None, str | None]:
    dates = sorted(
        p.stem.replace("ais_", "")
        for p in ais_dir.glob("ais_*.parquet")
        if re.fullmatch(r"ais_\d{4}-\d{2}-\d{2}", p.stem)
    )
    if not dates:
        return None, None
    return dates[0], dates[-1]


def trip_candidate_dates(trip: dict) -> list[str]:
    """Local report date plus prior days for multi-day / overnight trips."""
    d0 = datetime.strptime(trip["date"], "%Y-%m-%d").date()
    out = [d0.isoformat()]
    tt = (trip.get("trip_type") or "").lower()
    extra = 0
    if "1.5" in tt or "overnight" in tt:
        extra = max(extra, 1)
    if "2.5" in tt:
        extra = max(extra, 2)
    elif re.search(r"\b2\s*day\b", tt):
        extra = max(extra, 2)
    elif re.search(r"\b3\s*day\b", tt):
        extra = max(extra, 3)
    for i in range(1, extra + 1):
        out.append((d0 - timedelta(days=i)).isoformat())
    return out


def compact_stop(s: dict) -> dict:
    return {
        "lat": s["lat"],
        "lon": s["lon"],
        "duration_min": s["duration_min"],
        "start_utc": s["start_utc"],
        "end_utc": s["end_utc"],
        "grid_id": s["grid_id"],
        "ais_vessel_name": s["ais_vessel_name"],
        "mean_sog_kn": s["mean_sog_kn"],
        "n_points": s["n_points"],
        "date": s.get("date"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trips", type=Path, default=DATA_RAW / "fish_reports" / "trips.jsonl")
    ap.add_argument("--stops", type=Path, default=DATA_PROCESSED / "offshore_stops.json")
    ap.add_argument("--registry", type=Path, default=DATA_PROCESSED / "vessel_mmsi_registry.json")
    ap.add_argument("--ais-dir", type=Path, default=DATA_PROCESSED / "ais_daily")
    ap.add_argument("--out-dir", type=Path, default=DOCS_DATA)
    args = ap.parse_args()

    trips = load_trips(args.trips)
    stops = json.loads(args.stops.read_text()) if args.stops.exists() else []
    registry = json.loads(args.registry.read_text()) if args.registry.exists() else []
    accepted = build_accepted_names(args.trips)
    ais_start, ais_end = detect_ais_window(args.ais_dir)
    if not ais_start:
        ais_start, ais_end = PILOT_AIS_START, PILOT_AIS_END

    name_to_mmsi: dict[str, set[int]] = defaultdict(set)
    for r in registry:
        if r.get("match_confidence") not in ("high", "high_secondary"):
            continue
        mmsi = int(r["mmsi"])
        for bn in r.get("report_boat_names") or []:
            name_to_mmsi[normalize_name(bn)].add(mmsi)
        ais_norm = normalize_name(r.get("ais_vessel_name", ""))
        if ais_norm in accepted:
            name_to_mmsi[normalize_name(accepted[ais_norm])].add(mmsi)

    # Index stops by MMSI + Pacific local date (set in detect_stops).
    stops_by_key: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for s in stops:
        stops_by_key[(int(s["mmsi"]), s["date"][:10])].append(compact_stop(s))

    by_date: dict[str, list[dict]] = defaultdict(list)
    unmatched_trips = 0
    matched_with_stops = 0
    status_counts: dict[str, int] = defaultdict(int)

    for t in trips:
        key = normalize_name(t["boat_name"])
        mmsis = set(name_to_mmsi.get(key, set()))
        cand_dates = trip_candidate_dates(t)
        trip_stops = []
        seen = set()
        for m in sorted(mmsis):
            for d in cand_dates:
                for s in stops_by_key.get((m, d), []):
                    sid = (s["start_utc"], s["lat"], s["lon"])
                    if sid in seen:
                        continue
                    seen.add(sid)
                    trip_stops.append(s)

        in_ais_window = ais_start <= t["date"] <= ais_end
        if trip_stops:
            ais_status = "matched_stops"
            ais_status_detail = f"{len(trip_stops)} offshore AIS stop(s) (catch not split)"
            matched_with_stops += 1
        elif not mmsis:
            ais_status = "no_mmsi"
            ais_status_detail = "No AIS MMSI match for this boat name yet"
            unmatched_trips += 1
        elif not in_ais_window:
            ais_status = "outside_ais_window"
            ais_status_detail = (
                f"No AIS extract for {t['date']} (loaded {ais_start} → {ais_end})"
            )
        else:
            ais_status = "no_offshore_stop"
            ais_status_detail = (
                "AIS found for this boat/day, but no offshore stop ≥10 min "
                "(may be dockside-only, always moving, or AIS gap)"
            )
        status_counts[ais_status] += 1

        species_pp = t.get("species_per_person") or {}
        kept_species = [
            {
                "species": s["species"],
                "count": s["count"],
                "per_person": species_pp.get(s["species"]),
            }
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
                "ais_status": ais_status,
                "ais_status_detail": ais_status_detail,
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
        "ais_window": {"start": ais_start, "end": ais_end},
        "ais_availability_note": (
            "Free Marine Cadastre bulk AIS daily files used here currently run "
            "through 2025-12-31. Stops are dated in America/Los_Angeles."
        ),
        "methods": {
            "fish_per_person": "total kept fish / anglers from the dock total (direct)",
            "species_per_person": "species kept count / anglers (direct)",
            "offshore_stops": (
                "SOG <= configured max, duration >= configured min, outside home-dock "
                "radii; see scripts/config.py"
            ),
            "catch_location_attribution": (
                "NOT applied. Trip totals remain at voyage level. Location "
                "productivity will be estimated later by cross-vessel statistics."
            ),
            "day_join": (
                "Stops dated in America/Los_Angeles; multi-day/overnight trips also "
                "pull prior local days."
            ),
        },
        "home_docks": HOME_DOCKS,
        "dates": dates,
        "stats": {
            "n_days_with_reports": len(dates),
            "n_trips": len(trips),
            "n_offshore_stops": len(stops),
            "n_registry_vessels": len(registry),
            "n_trips_with_stops": matched_with_stops,
            "n_trips_unmatched_to_mmsi": unmatched_trips,
            "ais_status_counts": dict(status_counts),
        },
        "default_date": next(
            (d for d in reversed(dates) if ais_start <= d <= ais_end),
            dates[-1] if dates else None,
        ),
    }
    (args.out_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    debug = {
        "unmatched_boat_names": sorted(
            {t["boat_name"] for t in trips if not name_to_mmsi.get(normalize_name(t["boat_name"]))}
        ),
        "accepted_ais_name_keys": sorted(accepted.keys()),
        "vessel_aliases_config": VESSEL_ALIASES,
        "registry_non_high": [r for r in registry if r.get("match_confidence") not in ("high", "high_secondary")],
        "ais_status_counts": dict(status_counts),
        "notes": [
            "Edit FEEDBACK.md / scripts/config.py VESSEL_ALIASES to correct MMSI/boat matches.",
            "Stop dates use America/Los_Angeles.",
        ],
    }
    (DATA_PROCESSED / "join_debug.json").write_text(json.dumps(debug, indent=2))
    print(json.dumps(meta["stats"], indent=2))
    print(f"Wrote map data -> {args.out_dir}")


if __name__ == "__main__":
    main()
