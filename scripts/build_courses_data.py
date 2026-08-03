#!/usr/bin/env python3
"""Build fishing-day course polylines: home dock → offshore stops (time order) → home.

Uses existing day JSON join payloads (no full AIS track export). Each course is a
schematic trip path good for overlaying many days; date-filterable in the UI.
Also patches locations.json with first/last visit dates for the spots date slider.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from config import DOCS_DATA, HOME_DOCKS, PILOT_AIS_END, PILOT_AIS_START  # noqa: E402

# Prefer a primary dock per city; landing_name can override for Long Beach / San Pedro.
CITY_HOME = {
    "Redondo Beach": "Redondo Beach Sportfishing",
    "San Pedro": "22nd Street Landing (San Pedro)",
    "Long Beach": "Long Beach Sportfishing",
    "Marina Del Rey": "Marina Del Rey Sportfishing",
    "Newport Beach": "Newport Landing / Davey's Locker",
    "Dana Point": "Dana Wharf Sportfishing",
}

LANDING_HOME = {
    "pierpoint": "Pierpoint Landing (Long Beach)",
    "22nd street": "22nd Street Landing (San Pedro)",
    "la waterfront": "LA Waterfront / San Pedro",
    "long beach sportfishing": "Long Beach Sportfishing",
    "marina del rey": "Marina Del Rey Sportfishing",
    "newport landing": "Newport Landing / Davey's Locker",
    "davey's locker": "Newport Landing / Davey's Locker",
    "daveys locker": "Newport Landing / Davey's Locker",
    "dana wharf": "Dana Wharf Sportfishing",
    "redondo": "Redondo Beach Sportfishing",
}


def dock_by_name() -> dict[str, dict]:
    return {d["name"]: d for d in HOME_DOCKS}


def resolve_home(city: str | None, landing: str | None) -> dict | None:
    docks = dock_by_name()
    landing_l = (landing or "").lower()
    for key, name in LANDING_HOME.items():
        if key in landing_l and name in docks:
            return docks[name]
    name = CITY_HOME.get(city or "")
    return docks.get(name) if name else None


def build_course(trip: dict) -> dict | None:
    stops = list(trip.get("offshore_stops") or [])
    if not stops:
        return None
    home = resolve_home(trip.get("city"), trip.get("landing_name"))
    if not home:
        return None
    stops_sorted = sorted(stops, key=lambda s: s.get("start_utc") or "")
    line = [[home["lat"], home["lon"]]]
    for s in stops_sorted:
        line.append([round(float(s["lat"]), 5), round(float(s["lon"]), 5)])
    line.append([home["lat"], home["lon"]])
    mmsis = trip.get("mmsis") or []
    return {
        "date": trip["date"],
        "boat_name": trip["boat_name"],
        "city": trip.get("city"),
        "landing_name": trip.get("landing_name"),
        "mmsi": mmsis[0] if mmsis else None,
        "home_name": home["name"],
        "home": [home["lat"], home["lon"]],
        "line": line,
        "n_stops": len(stops_sorted),
        "fish_per_person": trip.get("fish_per_person"),
        "fish_per_person_hour": trip.get("fish_per_person_hour"),
        "trip_type": trip.get("trip_type"),
        "feature_ids": [
            s.get("feature_id") or s.get("grid_id")
            for s in stops_sorted
            if s.get("feature_id") or s.get("grid_id")
        ],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days-dir", type=Path, default=DOCS_DATA / "days")
    ap.add_argument("--out", type=Path, default=DOCS_DATA / "courses.json")
    ap.add_argument(
        "--locations",
        type=Path,
        default=DOCS_DATA / "locations.json",
        help="Patch first/last visit dates onto locations for the spots date slider",
    )
    args = ap.parse_args()

    courses = []
    feature_dates: dict[str, list[str]] = defaultdict(list)
    day_files = sorted(args.days_dir.glob("????-??-??.json"))
    for i, path in enumerate(day_files):
        day = json.loads(path.read_text())
        for trip in day.get("trips") or []:
            course = build_course(trip)
            if not course:
                continue
            # Drop local-day spill outside the AIS ingest window.
            if not (PILOT_AIS_START <= course["date"] <= PILOT_AIS_END):
                continue
            courses.append(course)
            for fid in course["feature_ids"]:
                feature_dates[fid].append(course["date"])
        if (i + 1) % 500 == 0:
            print(f"… {i + 1}/{len(day_files)} days, {len(courses)} courses", flush=True)

    courses.sort(key=lambda c: (c["date"], c["boat_name"]))
    # Clamp slider dates to the AIS ingest window (local-day edges can spill a day).
    dates = sorted(
        {
            c["date"]
            for c in courses
            if PILOT_AIS_START <= c["date"] <= PILOT_AIS_END
        }
    )
    if not dates:
        dates = sorted({c["date"] for c in courses})
    payload = {
        "description": (
            "Schematic fishing-day courses: home dock → offshore AIS stops "
            "(time order) → home dock. Not full AIS tracks."
        ),
        "n_courses": len(courses),
        "date_start": dates[0] if dates else None,
        "date_end": dates[-1] if dates else None,
        "ais_window": {"start": PILOT_AIS_START, "end": PILOT_AIS_END},
        "dates": dates,
        "courses": courses,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"Wrote {len(courses)} courses ({dates[0] if dates else '?'} → {dates[-1] if dates else '?'}) -> {args.out}")
    print(f"Size {args.out.stat().st_size / 1024 / 1024:.1f} MB")

    if args.locations.exists():
        loc_payload = json.loads(args.locations.read_text())
        patched = 0
        for loc in loc_payload.get("locations") or []:
            fid = loc.get("feature_id") or loc.get("grid_id")
            ds = sorted(set(feature_dates.get(fid) or []))
            if not ds:
                # Fall back to visits array if present.
                vs = sorted({v.get("date") for v in (loc.get("visits") or []) if v.get("date")})
                ds = vs
            if ds:
                loc["first_visit_date"] = ds[0]
                loc["last_visit_date"] = ds[-1]
                loc["n_visit_dates"] = len(ds)
                patched += 1
        args.locations.write_text(json.dumps(loc_payload, separators=(",", ":")))
        print(f"Patched first/last visit dates on {patched} locations -> {args.locations}")


if __name__ == "__main__":
    main()
