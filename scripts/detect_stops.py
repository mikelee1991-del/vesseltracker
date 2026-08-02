#!/usr/bin/env python3
"""Detect offshore stationary fishing stops from filtered AIS points."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

PACIFIC = ZoneInfo("America/Los_Angeles")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from config import (  # noqa: E402
    DATA_PROCESSED,
    FEATURE_CLUSTER_RADIUS_M,
    HOME_DOCKS,
    STOP_CLUSTER_RADIUS_M,
    STOP_GAP_MIN,
    STOP_MAX_SOG_KN,
    STOP_MIN_DURATION_MIN,
)
from feature_cluster import assign_feature_ids  # noqa: E402


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def near_home_dock(lat: float, lon: float) -> str | None:
    for d in HOME_DOCKS:
        if haversine_m(lat, lon, d["lat"], d["lon"]) <= d["radius_m"]:
            return d["name"]
    return None


def merge_low_speed_segments(df: pd.DataFrame) -> list[dict]:
    """df: one vessel, sorted by time, already low-speed rows only."""
    if df.empty:
        return []
    segments = []
    start_i = 0
    prev_t = df.iloc[0]["base_date_time"]
    for i in range(1, len(df)):
        t = df.iloc[i]["base_date_time"]
        gap_min = (t - prev_t).total_seconds() / 60.0
        if gap_min > STOP_GAP_MIN:
            segments.append((start_i, i - 1))
            start_i = i
        prev_t = t
    segments.append((start_i, len(df) - 1))

    stops = []
    for a, b in segments:
        seg = df.iloc[a : b + 1]
        t0 = seg.iloc[0]["base_date_time"]
        t1 = seg.iloc[-1]["base_date_time"]
        duration_min = (t1 - t0).total_seconds() / 60.0
        if duration_min < STOP_MIN_DURATION_MIN:
            continue
        lat = float(seg["latitude"].mean())
        lon = float(seg["longitude"].mean())
        dock = near_home_dock(lat, lon)
        if dock:
            continue
        # Fish reports use local calendar days; date stops in Pacific time.
        date_pacific = t0.tz_convert(PACIFIC).date().isoformat()
        date_utc = t0.date().isoformat()
        stops.append(
            {
                "mmsi": int(seg.iloc[0]["mmsi"]),
                "ais_vessel_name": seg.iloc[0]["vessel_name"],
                "start_utc": t0.isoformat(),
                "end_utc": t1.isoformat(),
                "duration_min": round(duration_min, 1),
                "lat": lat,
                "lon": lon,
                "n_points": int(len(seg)),
                "mean_sog_kn": round(float(seg["sog"].mean()), 3),
                "date": date_pacific,
                "date_utc": date_utc,
            }
        )
    return stops


def cluster_label(lat: float, lon: float, radius_m: float = STOP_CLUSTER_RADIUS_M) -> str:
    # Simple equal-area-ish grid for pilot visualization / later productivity stats.
    # ~1 deg lat ~= 111_320 m
    dlat = radius_m / 111320.0
    dlon = radius_m / (111320.0 * max(0.2, math.cos(math.radians(lat))))
    i = int(math.floor(lat / dlat))
    j = int(math.floor(lon / dlon))
    return f"g_{i}_{j}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ais-dir", type=Path, default=DATA_PROCESSED / "ais_daily")
    ap.add_argument("--registry", type=Path, default=DATA_PROCESSED / "vessel_mmsi_registry.json")
    ap.add_argument("--out", type=Path, default=DATA_PROCESSED / "offshore_stops.json")
    args = ap.parse_args()

    files = sorted(args.ais_dir.glob("ais_*.parquet"))
    if not files:
        print("No AIS parquet files found.", file=sys.stderr)
        sys.exit(2)

    allowed = None
    if args.registry.exists():
        reg = json.loads(args.registry.read_text())
        allowed = {
            int(r["mmsi"])
            for r in reg
            if r.get("match_confidence") in ("high", "high_secondary")
        }
        print(f"Restricting stops to {len(allowed)} registry MMSIs")

    con = duckdb.connect()
    glob = (args.ais_dir / "ais_*.parquet").as_posix()
    df = con.execute(
        f"""
        SELECT *
        FROM read_parquet('{glob}')
        WHERE sog IS NOT NULL AND sog <= {STOP_MAX_SOG_KN}
        ORDER BY mmsi, base_date_time
        """
    ).fetchdf()
    if allowed is not None:
        df = df[df["mmsi"].isin(allowed)]
    df["base_date_time"] = pd.to_datetime(df["base_date_time"], utc=True)

    all_stops: list[dict] = []
    for mmsi, g in df.groupby("mmsi"):
        all_stops.extend(merge_low_speed_segments(g.reset_index(drop=True)))

    for s in all_stops:
        s["grid_id"] = cluster_label(s["lat"], s["lon"])
    assign_feature_ids(all_stops, FEATURE_CLUSTER_RADIUS_M)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(all_stops, indent=2))
    n_features = len({s["feature_id"] for s in all_stops})
    print(
        f"Wrote {len(all_stops)} offshore stops / {n_features} features "
        f"(radius {FEATURE_CLUSTER_RADIUS_M:.2f} m) -> {args.out}"
    )


if __name__ == "__main__":
    main()
