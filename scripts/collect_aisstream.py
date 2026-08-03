#!/usr/bin/env python3
"""Collect live SoCal AIS from free aisstream.io websocket into daily parquet.

This is the free forward-looking alternative while Marine Cadastre 2026 bulk
files are unpublished. aisstream has NO historical backfill API — it only
streams live messages. Run continuously (or on a host with long sessions)
to build our own archive.

Setup:
  1. Create a free API key at https://aisstream.io/ (GitHub login)
  2. export AISSTREAM_API_KEY=...
  3. python3 scripts/collect_aisstream.py --hours 6

Output lands in data/processed/ais_daily/ais_YYYY-MM-DD.parquet with schema
compatible with detect_stops.py (plus ais_source='aisstream').
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from config import (  # noqa: E402
    AIS_BBOX,
    DATA_PROCESSED,
    DATA_RAW,
    MMSI_ALLOWLIST,
    MMSI_TO_REPORT_BOAT,
)
from extract_ais import build_accepted_names, normalize_name  # noqa: E402

try:
    from websockets.sync.client import connect as ws_connect
except ImportError as e:  # pragma: no cover
    raise SystemExit("Install dependency: pip install websockets") from e

WS_URL = "wss://stream.aisstream.io/v0/stream"
OUT_DIR = DATA_PROCESSED / "ais_daily"


def bbox_for_aisstream() -> list[list[list[float]]]:
    # aisstream bbox corners: [[lat, lon], [lat, lon]]
    return [[
        [AIS_BBOX["min_lat"], AIS_BBOX["min_lon"]],
        [AIS_BBOX["max_lat"], AIS_BBOX["max_lon"]],
    ]]


def parse_message(msg: dict, accepted: dict[str, str]) -> dict | None:
    meta = msg.get("MetaData") or {}
    mmsi = meta.get("MMSI") or meta.get("Mmsi")
    if mmsi is None:
        return None
    try:
        mmsi = int(mmsi)
    except (TypeError, ValueError):
        return None

    body = msg.get("Message") or {}
    pos = (
        body.get("PositionReport")
        or body.get("StandardClassBPositionReport")
        or body.get("ExtendedClassBPositionReport")
        or {}
    )
    static = body.get("ShipStaticData") or {}

    lat = meta.get("latitude", meta.get("Latitude"))
    lon = meta.get("longitude", meta.get("Longitude"))
    if lat is None:
        lat = pos.get("Latitude", pos.get("latitude"))
    if lon is None:
        lon = pos.get("Longitude", pos.get("longitude"))
    if lat is None or lon is None:
        return None
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return None
    if not (AIS_BBOX["min_lat"] <= lat_f <= AIS_BBOX["max_lat"]):
        return None
    if not (AIS_BBOX["min_lon"] <= lon_f <= AIS_BBOX["max_lon"]):
        return None

    name = (
        meta.get("ShipName")
        or meta.get("shipName")
        or static.get("Name")
        or static.get("ShipName")
        or ""
    )
    name = str(name).strip()
    norm = normalize_name(name) if name else ""
    report = MMSI_TO_REPORT_BOAT.get(mmsi) or accepted.get(norm)
    if report is None and mmsi not in MMSI_ALLOWLIST and norm not in accepted:
        return None

    sog = pos.get("Sog", pos.get("SOG", meta.get("Sog")))
    cog = pos.get("Cog", pos.get("COG", meta.get("Cog")))
    heading = pos.get("TrueHeading", pos.get("Heading", meta.get("heading")))
    ts = meta.get("time_utc") or meta.get("time")
    try:
        ts_clean = str(ts).replace(" +0000 UTC", "").replace(" UTC", "").strip()
        dt = pd.to_datetime(ts_clean, utc=True)
    except Exception:
        dt = pd.Timestamp.now(tz="UTC")

    dim = static.get("Dimension") or {}
    return {
        "mmsi": mmsi,
        "base_date_time": dt.to_pydatetime(),
        "longitude": lon_f,
        "latitude": lat_f,
        "sog": float(sog) if sog is not None else None,
        "cog": float(cog) if cog is not None else None,
        "heading": float(heading) if heading is not None else None,
        "vessel_name": name or None,
        "call_sign": static.get("CallSign") or meta.get("callSign"),
        "vessel_type": static.get("Type") or meta.get("Type"),
        "status": pos.get("NavigationalStatus"),
        "length": dim.get("A"),
        "width": dim.get("B"),
        "draft": static.get("MaximumStaticDraught"),
        "transceiver": None,
        "vessel_name_norm": norm or None,
        "report_boat_name": report,
        "date": pd.Timestamp(dt).tz_convert("UTC").strftime("%Y-%m-%d"),
        "ais_source": "aisstream",
    }


def flush_day_buffers(buffers: dict[str, list[dict]], out_dir: Path) -> int:
    written = 0
    out_dir.mkdir(parents=True, exist_ok=True)
    for day, rows in list(buffers.items()):
        if not rows:
            continue
        path = out_dir / f"ais_{day}.parquet"
        new_df = pd.DataFrame(rows)
        if path.exists():
            old = pd.read_parquet(path)
            merged = pd.concat([old, new_df], ignore_index=True)
        else:
            merged = new_df
        merged["base_date_time"] = pd.to_datetime(merged["base_date_time"], utc=True)
        merged = merged.drop_duplicates(
            subset=["mmsi", "base_date_time", "latitude", "longitude"],
            keep="last",
        ).sort_values(["mmsi", "base_date_time"])
        merged.to_parquet(path, index=False)
        written += len(rows)
        buffers[day] = []
        print(f"flushed {len(rows)} rows -> {path} (total {len(merged)})", flush=True)
    return written


def collect(api_key: str, hours: float, flush_every: int, accepted: dict[str, str]) -> None:
    sub = {
        "APIKey": api_key,
        "BoundingBoxes": bbox_for_aisstream(),
        "FilterMessageTypes": [
            "PositionReport",
            "StandardClassBPositionReport",
            "ExtendedClassBPositionReport",
            "ShipStaticData",
        ],
    }
    buffers: dict[str, list[dict]] = defaultdict(list)
    deadline = time.time() + hours * 3600
    total = 0
    kept = 0

    print(
        f"Connecting aisstream bbox "
        f"lat[{AIS_BBOX['min_lat']},{AIS_BBOX['max_lat']}] "
        f"lon[{AIS_BBOX['min_lon']},{AIS_BBOX['max_lon']}] "
        f"for {hours}h…",
        flush=True,
    )

    while time.time() < deadline:
        try:
            with ws_connect(WS_URL, open_timeout=30, close_timeout=5) as ws:
                ws.send(json.dumps(sub))
                print("subscribed", flush=True)
                while time.time() < deadline:
                    try:
                        raw = ws.recv(timeout=30)
                    except TimeoutError:
                        continue
                    total += 1
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if msg.get("error") or msg.get("Error"):
                        print("aisstream error:", msg, flush=True)
                        time.sleep(5)
                        break
                    row = parse_message(msg, accepted)
                    if not row:
                        continue
                    buffers[row["date"]].append(row)
                    kept += 1
                    if kept % flush_every == 0:
                        flush_day_buffers(buffers, OUT_DIR)
                        print(f"progress messages={total} kept={kept}", flush=True)
        except Exception as exc:
            print(f"[warn] websocket error: {exc}; reconnecting in 5s", flush=True)
            flush_day_buffers(buffers, OUT_DIR)
            time.sleep(5)

    flush_day_buffers(buffers, OUT_DIR)
    print(f"done messages={total} kept={kept}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--api-key", default=os.environ.get("AISSTREAM_API_KEY", ""))
    ap.add_argument("--hours", type=float, default=1.0, help="How long to collect")
    ap.add_argument("--flush-every", type=int, default=200)
    ap.add_argument("--trips", type=Path, default=DATA_RAW / "fish_reports" / "trips.jsonl")
    args = ap.parse_args()
    if not args.api_key:
        raise SystemExit(
            "Set AISSTREAM_API_KEY or pass --api-key.\n"
            "Free key: https://aisstream.io/ (sign in → API Keys)"
        )
    accepted = build_accepted_names(args.trips)
    collect(args.api_key, args.hours, args.flush_every, accepted)


if __name__ == "__main__":
    main()
