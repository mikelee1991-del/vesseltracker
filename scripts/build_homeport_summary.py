#!/usr/bin/env python3
"""Build docs/data/homeport_summary.json from fish-report dock totals.

No AIS required — rolls up recent catch by homeport (city section) from the
socalfishreports scrape so the Catch tab works when Cadastre coverage is thin.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from config import DOCS_DATA, TARGET_CITIES  # noqa: E402
from trip_duration import fish_per_person_hour  # noqa: E402
from trips_io import load_trips, trip_jsonl_paths  # noqa: E402

WINDOWS_DAYS = (7, 14, 30, 60)
TOP_SPECIES = 8
TOP_BOATS = 8


def parse_iso(iso: str) -> date:
    return datetime.strptime(iso, "%Y-%m-%d").date()


def iso(d: date) -> str:
    return d.isoformat()


def blank_bucket() -> dict:
    return {
        "n_trips": 0,
        "anglers": 0,
        "fish_kept": 0,
        "fpp_sum": 0.0,
        "fpp_n": 0,
        "fph_sum": 0.0,
        "fph_n": 0,
        "boats": set(),
        "days": set(),
        "species": defaultdict(float),
        "boat_stats": defaultdict(lambda: {
            "n_trips": 0,
            "fish_kept": 0,
            "anglers": 0,
            "fpp_sum": 0.0,
            "fpp_n": 0,
        }),
        "landing_stats": defaultdict(lambda: {
            "n_trips": 0,
            "fish_kept": 0,
            "anglers": 0,
            "boats": set(),
        }),
    }


def ingest_trip(bucket: dict, trip: dict) -> None:
    fish = float(trip.get("total_fish_kept") or 0)
    anglers = int(trip.get("anglers") or 0)
    boat = (trip.get("boat_name") or "").strip() or "(unnamed)"
    landing = (trip.get("landing_name") or "").strip() or "(unknown landing)"
    fpp = trip.get("fish_per_person")
    if fpp is None and anglers > 0:
        fpp = fish / anglers
    fph = trip.get("fish_per_person_hour")
    if fph is None and fpp is not None:
        fph = fish_per_person_hour(float(fpp), trip.get("trip_type"))

    bucket["n_trips"] += 1
    bucket["anglers"] += anglers
    bucket["fish_kept"] += fish
    bucket["boats"].add(boat)
    if trip.get("date"):
        bucket["days"].add(trip["date"])
    if fpp is not None:
        bucket["fpp_sum"] += float(fpp)
        bucket["fpp_n"] += 1
    if fph is not None:
        bucket["fph_sum"] += float(fph)
        bucket["fph_n"] += 1

    for sp in trip.get("species") or []:
        name = (sp.get("species") or "").strip()
        if not name:
            continue
        # Prefer kept fish; scrape marks released separately.
        if sp.get("released"):
            continue
        bucket["species"][name] += float(sp.get("count") or 0)

    bs = bucket["boat_stats"][boat]
    bs["n_trips"] += 1
    bs["fish_kept"] += fish
    bs["anglers"] += anglers
    if fpp is not None:
        bs["fpp_sum"] += float(fpp)
        bs["fpp_n"] += 1

    ls = bucket["landing_stats"][landing]
    ls["n_trips"] += 1
    ls["fish_kept"] += fish
    ls["anglers"] += anglers
    ls["boats"].add(boat)


def finalize_bucket(name_key: str, name: str, bucket: dict) -> dict:
    mean_fpp = (bucket["fpp_sum"] / bucket["fpp_n"]) if bucket["fpp_n"] else None
    mean_fph = (bucket["fph_sum"] / bucket["fph_n"]) if bucket["fph_n"] else None
    species_top = sorted(bucket["species"].items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_SPECIES]
    boats_top = sorted(
        (
            {
                "boat_name": boat,
                "n_trips": st["n_trips"],
                "fish_kept": round(st["fish_kept"], 1),
                "anglers": st["anglers"],
                "mean_fpp": round(st["fpp_sum"] / st["fpp_n"], 2) if st["fpp_n"] else None,
            }
            for boat, st in bucket["boat_stats"].items()
        ),
        key=lambda r: (-r["fish_kept"], -r["n_trips"], r["boat_name"]),
    )[:TOP_BOATS]
    by_landing = sorted(
        (
            {
                "landing_name": landing,
                "n_trips": st["n_trips"],
                "n_boats": len(st["boats"]),
                "anglers": st["anglers"],
                "fish_kept": round(st["fish_kept"], 1),
            }
            for landing, st in bucket["landing_stats"].items()
        ),
        key=lambda r: (-r["fish_kept"], -r["n_trips"], r["landing_name"]),
    )
    return {
        name_key: name,
        "n_trips": bucket["n_trips"],
        "n_boats": len(bucket["boats"]),
        "n_days": len(bucket["days"]),
        "anglers": bucket["anglers"],
        "fish_kept": round(bucket["fish_kept"], 1),
        "mean_fpp": round(mean_fpp, 2) if mean_fpp is not None else None,
        "mean_fph": round(mean_fph, 2) if mean_fph is not None else None,
        "species_top": [{"species": s, "count": round(c, 1)} for s, c in species_top],
        "boats_top": boats_top,
        "by_landing": by_landing,
    }


def max_trip_date(trips_arg: Path) -> str | None:
    mx = None
    for path in trip_jsonl_paths(trips_arg):
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line).get("date")
                except Exception:
                    continue
                if d and (mx is None or d > mx):
                    mx = d
    return mx


def build(trips: list[dict], as_of: str, cities: set[str]) -> dict:
    as_of_d = parse_iso(as_of)
    windows: dict[str, dict] = {}
    for days in WINDOWS_DAYS:
        start = iso(as_of_d - timedelta(days=days - 1))
        city_buckets: dict[str, dict] = {c: blank_bucket() for c in cities}
        fleet = blank_bucket()
        n_in = 0
        for trip in trips:
            d = trip.get("date")
            if not d or d < start or d > as_of:
                continue
            city = trip.get("city")
            if city not in cities:
                continue
            ingest_trip(city_buckets[city], trip)
            ingest_trip(fleet, trip)
            n_in += 1
        by_city = sorted(
            (finalize_bucket("city", city, city_buckets[city]) for city in cities if city_buckets[city]["n_trips"]),
            key=lambda r: (-r["fish_kept"], -r["n_trips"], r["city"]),
        )
        windows[str(days)] = {
            "days": days,
            "start": start,
            "end": as_of,
            "n_trips": n_in,
            "n_boats": len(fleet["boats"]),
            "anglers": fleet["anglers"],
            "fish_kept": round(fleet["fish_kept"], 1),
            "mean_fpp": round(fleet["fpp_sum"] / fleet["fpp_n"], 2) if fleet["fpp_n"] else None,
            "by_city": by_city,
        }

    # Calendar YTD for the as_of year (still dock totals only).
    ytd_start = f"{as_of_d.year}-01-01"
    city_buckets = {c: blank_bucket() for c in cities}
    fleet = blank_bucket()
    n_in = 0
    for trip in trips:
        d = trip.get("date")
        if not d or d < ytd_start or d > as_of:
            continue
        city = trip.get("city")
        if city not in cities:
            continue
        ingest_trip(city_buckets[city], trip)
        ingest_trip(fleet, trip)
        n_in += 1
    windows["ytd"] = {
        "days": None,
        "label": f"{as_of_d.year} YTD",
        "start": ytd_start,
        "end": as_of,
        "n_trips": n_in,
        "n_boats": len(fleet["boats"]),
        "anglers": fleet["anglers"],
        "fish_kept": round(fleet["fish_kept"], 1),
        "mean_fpp": round(fleet["fpp_sum"] / fleet["fpp_n"], 2) if fleet["fpp_n"] else None,
        "by_city": sorted(
            (finalize_bucket("city", city, city_buckets[city]) for city in cities if city_buckets[city]["n_trips"]),
            key=lambda r: (-r["fish_kept"], -r["n_trips"], r["city"]),
        ),
    }

    return {
        "title": "Recent catch by homeport",
        "description": (
            "Dock totals from socalfishreports.com rolled up by city (homeport). "
            "No AIS required — useful when Marine Cadastre coverage is missing."
        ),
        "as_of": as_of,
        "source": "socalfishreports.com dock totals",
        "cities": sorted(cities),
        "default_window": "14",
        "windows": windows,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--trips",
        type=Path,
        default=ROOT / "data" / "raw" / "fish_reports" / "by_year",
        help="Trip JSONL file or by_year directory",
    )
    ap.add_argument("--as-of", default=None, help="End date YYYY-MM-DD (default: latest trip date)")
    ap.add_argument(
        "--out",
        type=Path,
        default=DOCS_DATA / "homeport_summary.json",
        help="Output JSON path",
    )
    args = ap.parse_args()

    as_of = args.as_of or max_trip_date(args.trips)
    if not as_of:
        raise SystemExit("No trip dates found — scrape fish reports first.")

    as_of_d = parse_iso(as_of)
    earliest = min(date(as_of_d.year, 1, 1), as_of_d - timedelta(days=max(WINDOWS_DAYS) - 1))
    all_trips = load_trips(args.trips)
    trips = [
        t for t in all_trips
        if t.get("date") and earliest.isoformat() <= t["date"] <= as_of
    ]

    payload = build(trips, as_of, set(TARGET_CITIES))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        f"Wrote {args.out} as_of={as_of} "
        f"windows={list(payload['windows'])} "
        f"trips_in_scope={len(trips)}"
    )


if __name__ == "__main__":
    main()
