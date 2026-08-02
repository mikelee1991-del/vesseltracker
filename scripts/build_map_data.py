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
    FEATURE_CLUSTER_RADIUS_FT,
    FEATURE_CLUSTER_RADIUS_M,
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
from feature_cluster import assign_feature_ids, haversine_m  # noqa: E402


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
        "grid_id": s.get("grid_id"),
        "feature_id": s.get("feature_id"),
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
    # Re-cluster with current radius so config changes apply on rebuild.
    if stops:
        assign_feature_ids(stops, FEATURE_CLUSTER_RADIUS_M)
        args.stops.write_text(json.dumps(stops, indent=2))
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

    # Feature-centric aggregate: stops within FEATURE_CLUSTER_RADIUS_M are one
    # underwater spot. Trip FPP is visit context only — not a location catch rate.
    loc_map: dict[str, dict] = {}
    for d, trips_d in by_date.items():
        for t in trips_d:
            for s in t.get("offshore_stops") or []:
                fid = s.get("feature_id") or s.get("grid_id") or (
                    f"pt_{round(s['lat'], 3)}_{round(s['lon'], 3)}"
                )
                loc = loc_map.setdefault(
                    fid,
                    {
                        "feature_id": fid,
                        "lat_sum": 0.0,
                        "lon_sum": 0.0,
                        "n_stops": 0,
                        "total_dwell_min": 0.0,
                        "boats": set(),
                        "dates": set(),
                        "visits": [],
                        "fpp_values": [],
                        "species_totals": defaultdict(float),
                        "stop_points": [],
                    },
                )
                loc["lat_sum"] += s["lat"]
                loc["lon_sum"] += s["lon"]
                loc["n_stops"] += 1
                loc["total_dwell_min"] += float(s.get("duration_min") or 0)
                loc["boats"].add(t["boat_name"])
                loc["dates"].add(d)
                loc["stop_points"].append((s["lat"], s["lon"]))
                visit = {
                    "date": d,
                    "boat_name": t["boat_name"],
                    "city": t["city"],
                    "anglers": t["anglers"],
                    "trip_type": t["trip_type"],
                    "fish_per_person": t["fish_per_person"],
                    "total_fish_kept": t["total_fish_kept"],
                    "duration_min": s.get("duration_min"),
                    "species": t.get("species") or [],
                }
                loc["visits"].append(visit)
                if t["fish_per_person"] is not None:
                    loc["fpp_values"].append(t["fish_per_person"])
                for sp in t.get("species") or []:
                    loc["species_totals"][sp["species"]] += float(sp.get("count") or 0)

    locations = []
    for fid, loc in loc_map.items():
        n = loc["n_stops"]
        lat = loc["lat_sum"] / n
        lon = loc["lon_sum"] / n
        # Max distance from centroid to a member stop (cluster footprint).
        spread_m = 0.0
        for plat, plon in loc["stop_points"]:
            spread_m = max(spread_m, haversine_m(lat, lon, plat, plon))
        fpp_vals = loc["fpp_values"]
        species_top = sorted(
            ({"species": k, "count": round(v, 1)} for k, v in loc["species_totals"].items()),
            key=lambda x: -x["count"],
        )[:8]
        locations.append(
            {
                "feature_id": fid,
                # Keep grid_id alias so older UI bits still key correctly.
                "grid_id": fid,
                "lat": lat,
                "lon": lon,
                "n_stops": n,
                "n_boat_days": len(loc["visits"]),
                "n_boats": len(loc["boats"]),
                "n_days": len(loc["dates"]),
                "total_dwell_min": round(loc["total_dwell_min"], 1),
                "cluster_spread_m": round(spread_m, 1),
                "cluster_radius_m": FEATURE_CLUSTER_RADIUS_M,
                "mean_trip_fpp": (sum(fpp_vals) / len(fpp_vals)) if fpp_vals else None,
                "median_trip_fpp": (
                    sorted(fpp_vals)[len(fpp_vals) // 2] if fpp_vals else None
                ),
                "boats": sorted(loc["boats"]),
                "species_top": species_top,
                "visits": sorted(loc["visits"], key=lambda v: (v["date"], v["boat_name"])),
                "fpp_note": (
                    "mean_trip_fpp is the average fish/person of dock totals for "
                    "boat-days that stopped here — not catch attributed to this spot"
                ),
            }
        )
    locations.sort(key=lambda x: (-x["total_dwell_min"], -x["n_stops"]))
    (args.out_dir / "locations.json").write_text(
        json.dumps(
            {
                "cluster_radius_m": FEATURE_CLUSTER_RADIUS_M,
                "cluster_radius_ft": FEATURE_CLUSTER_RADIUS_FT,
                "cluster_method": (
                    "centroid-bounded cluster of AIS stop positions within "
                    f"{FEATURE_CLUSTER_RADIUS_FT} ft / {FEATURE_CLUSTER_RADIUS_M:.2f} m "
                    "of a shared centroid (AIS positional noise; same underwater feature)"
                ),
                "locations": locations,
            }
        )
    )

    meta = {
        "title": "LA-area sportfishing take (pilot)",
        "description": (
            "Feature-centric view of AIS offshore stops clustered by proximity "
            f"({FEATURE_CLUSTER_RADIUS_FT} ft) and joined to socalfishreports.com "
            "dock totals. Catch counts are NOT split across stop locations; "
            "trip fish/person is shown as visit context."
        ),
        "sources": {
            "fish_reports": FISH_REPORT_SOURCE,
            "ais": "NOAA Marine Cadastre / U.S. Coast Guard NAIS daily CSV (1-minute sample)",
            "bathymetry": (
                "Zoomable NCEI DEM_all ColorHillshade tiles (≤3″ coastal DEMs) "
                "+ BlueTopo WMS elevation/hillshade + BAG survey hillshade"
            ),
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
            "feature_clustering": (
                f"Centroid-bounded cluster of stop positions within "
                f"{FEATURE_CLUSTER_RADIUS_FT} ft ({FEATURE_CLUSTER_RADIUS_M:.2f} m) "
                "of a shared centroid; absorbs AIS/GPS scatter for revisits to the "
                "same place without chaining along a reef."
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
        "feature_cluster_radius_m": FEATURE_CLUSTER_RADIUS_M,
        "feature_cluster_radius_ft": FEATURE_CLUSTER_RADIUS_FT,
        "home_docks": HOME_DOCKS,
        "dates": dates,
        "stats": {
            "n_days_with_reports": len(dates),
            "n_trips": len(trips),
            "n_offshore_stops": len(stops),
            "n_features": len(locations),
            "n_locations": len(locations),
            "n_registry_vessels": len(registry),
            "n_trips_with_stops": matched_with_stops,
            "n_trips_unmatched_to_mmsi": unmatched_trips,
            "ais_status_counts": dict(status_counts),
        },
        "default_date": next(
            (d for d in reversed(dates) if ais_start <= d <= ais_end),
            dates[-1] if dates else None,
        ),
        "default_view": "locations",
        "boats": sorted({t["boat_name"] for t in trips}),
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
    # Keep the human MMSI verification tool in sync with the latest join.
    try:
        from export_unmatched_boats import main as export_unmatched_main  # noqa: E402

        export_unmatched_main()
    except Exception as exc:  # pragma: no cover - best-effort side export
        print(f"Warning: unmatched_boats export failed: {exc}")
    print(json.dumps(meta["stats"], indent=2))
    print(f"Wrote map data -> {args.out_dir}")


if __name__ == "__main__":
    main()
