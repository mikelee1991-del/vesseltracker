"""Dwell-share catch attribution across a trip's offshore AIS stops.

Trip catch (dock totals) stays authoritative. When a trip has multiple offshore
stops, we allocate that trip's catch / angler-hours across features using each
feature's share of total AIS offshore dwell:

  share_f = dwell_min_f / sum(dwell_min over offshore stops)
  attributed_fish_f = total_fish_kept * share_f
  attributed_angler_hours_f = anglers * nominal_trip_hours * share_f

Spot fish/person/hour is then sum(attributed_fish) / sum(attributed_angler_hours)
across visits — a dwell-weighted blend of visiting trips' rates.

Trips with no offshore stops (or zero dwell) cannot be attributed to spots.
"""

from __future__ import annotations

from collections import defaultdict


def feature_id_for_stop(stop: dict) -> str:
    return (
        stop.get("feature_id")
        or stop.get("grid_id")
        or f"pt_{round(float(stop['lat']), 3)}_{round(float(stop['lon']), 3)}"
    )


def annotate_stops_with_dwell_share(stops: list[dict]) -> float:
    """Mutate stops with dwell_share (fraction of trip offshore dwell). Returns total dwell min."""
    total = sum(float(s.get("duration_min") or 0) for s in stops)
    for s in stops:
        dur = float(s.get("duration_min") or 0)
        s["dwell_share"] = (dur / total) if total > 0 else None
    return total


def feature_dwell_shares(stops: list[dict]) -> dict[str, float]:
    """feature_id -> share of trip offshore dwell (sums to 1 when total dwell > 0)."""
    total = sum(float(s.get("duration_min") or 0) for s in stops)
    if total <= 0:
        return {}
    by_f: dict[str, float] = defaultdict(float)
    for s in stops:
        by_f[feature_id_for_stop(s)] += float(s.get("duration_min") or 0)
    return {fid: dwell / total for fid, dwell in by_f.items()}


def attribute_trip_to_features(trip: dict, stops: list[dict]) -> list[dict]:
    """One row per feature visited on this trip, with dwell-share attribution.

    Returns list of dicts:
      feature_id, dwell_min, dwell_share, attributed_fish, attributed_fish_per_person,
      attributed_angler_hours, lat/lon centroid of stops at that feature, n_stops
    """
    if not stops:
        return []
    total_dwell = sum(float(s.get("duration_min") or 0) for s in stops)
    if total_dwell <= 0:
        return []

    anglers = trip.get("anglers")
    trip_hours = trip.get("trip_hours_nominal")
    fpp = trip.get("fish_per_person")
    total_fish = trip.get("total_fish_kept")
    species = trip.get("species") or []

    buckets: dict[str, dict] = {}
    for s in stops:
        fid = feature_id_for_stop(s)
        b = buckets.setdefault(
            fid,
            {
                "feature_id": fid,
                "dwell_min": 0.0,
                "lat_sum": 0.0,
                "lon_sum": 0.0,
                "n_stops": 0,
                "stop_points": [],
            },
        )
        dur = float(s.get("duration_min") or 0)
        b["dwell_min"] += dur
        b["lat_sum"] += float(s["lat"])
        b["lon_sum"] += float(s["lon"])
        b["n_stops"] += 1
        b["stop_points"].append((float(s["lat"]), float(s["lon"])))

    out = []
    for fid, b in buckets.items():
        share = b["dwell_min"] / total_dwell
        attributed_fish = (
            float(total_fish) * share if total_fish is not None else None
        )
        attributed_fpp = float(fpp) * share if fpp is not None else None
        attributed_hours = None
        if (
            anglers is not None
            and trip_hours is not None
            and float(anglers) > 0
            and float(trip_hours) > 0
        ):
            attributed_hours = float(anglers) * float(trip_hours) * share

        attributed_species = [
            {
                "species": sp["species"],
                "count": round(float(sp.get("count") or 0) * share, 3),
                "per_person": (
                    round(float(sp["per_person"]) * share, 4)
                    if sp.get("per_person") is not None
                    else None
                ),
            }
            for sp in species
        ]

        out.append(
            {
                "feature_id": fid,
                "dwell_min": round(b["dwell_min"], 1),
                "dwell_share": round(share, 6),
                "n_stops": b["n_stops"],
                "lat": b["lat_sum"] / b["n_stops"],
                "lon": b["lon_sum"] / b["n_stops"],
                "stop_points": b["stop_points"],
                "attributed_fish": (
                    round(attributed_fish, 3) if attributed_fish is not None else None
                ),
                "attributed_fish_per_person": (
                    round(attributed_fpp, 4) if attributed_fpp is not None else None
                ),
                "attributed_angler_hours": (
                    round(attributed_hours, 4) if attributed_hours is not None else None
                ),
                "attributed_species": attributed_species,
            }
        )
    return out
