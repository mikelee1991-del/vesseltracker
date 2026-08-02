#!/usr/bin/env python3
"""
Extract Marine Cadastre daily AIS broadcasts for LA-area charter vessels.

Uses DuckDB + httpfs to stream-filter remote .csv.zst files (1-minute NAIS
sample). Only rows matching the SoCal bbox and fleet name/MMSI filters are
kept. Designed to scale day-by-day without retaining national raw files.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from config import (  # noqa: E402
    AIS_BASE_URL,
    AIS_BBOX,
    AIS_FILENAME,
    DATA_PROCESSED,
    DATA_RAW,
    PILOT_AIS_END,
    PILOT_AIS_START,
)

NAME_NORMALIZE_RE = re.compile(r"[^A-Z0-9]+")


def daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def normalize_name(name: str) -> str:
    return NAME_NORMALIZE_RE.sub("", (name or "").upper())


def load_fleet_names(trips_path: Path) -> set[str]:
    names: set[str] = set()
    if not trips_path.exists():
        return names
    with trips_path.open() as f:
        for line in f:
            row = json.loads(line)
            n = normalize_name(row.get("boat_name", ""))
            if n:
                names.add(n)
    return names


def aliases_for(name: str) -> set[str]:
    """Common AIS vs fish-report naming differences."""
    n = normalize_name(name)
    out = {n}
    # REDONDO SPECIAL often broadcasts as REDONDO
    if n.endswith("SPECIAL"):
        out.add(n[: -len("SPECIAL")])
    if n.startswith("NEW"):
        out.add(n[3:])
    # Parenthetical disambiguators: PATRIOTNEWPORT -> PATRIOT
    for suf in ("NEWPORT", "VENTURA", "MB", "LB"):
        if n.endswith(suf) and len(n) > len(suf) + 2:
            out.add(n[: -len(suf)])
    return {x for x in out if x}


def build_match_sql(fleet_norms: set[str]) -> str:
    # Match when normalized AIS vessel_name equals or contains a fleet name,
    # or vice versa for short AIS names like REDONDO.
    # Implemented in Python after a broader SQL name filter for speed.
    return ""


def extract_day(con: duckdb.DuckDBPyConnection, day: date, fleet_norms: set[str], out_dir: Path) -> dict:
    out_path = out_dir / f"ais_{day.isoformat()}.parquet"
    if out_path.exists():
        # Already extracted.
        n = con.execute(f"SELECT count(*) FROM read_parquet('{out_path.as_posix()}')").fetchone()[0]
        return {"date": day.isoformat(), "rows": int(n), "path": str(out_path), "skipped": True}

    url = f"{AIS_BASE_URL}/{AIS_FILENAME.format(date=day.isoformat())}"
    bbox = AIS_BBOX
    # Broad SQL filter: SoCal bbox. Name filter applied in Python for fuzzy match.
    q = f"""
    SELECT
      mmsi,
      base_date_time,
      longitude,
      latitude,
      sog,
      cog,
      heading,
      vessel_name,
      call_sign,
      vessel_type,
      status,
      length,
      width,
      draft,
      transceiver
    FROM read_csv('{url}', compression='zstd', parallel=true, ignore_errors=true)
    WHERE longitude BETWEEN {bbox['min_lon']} AND {bbox['max_lon']}
      AND latitude BETWEEN {bbox['min_lat']} AND {bbox['max_lat']}
      AND vessel_name IS NOT NULL
    """
    df = con.execute(q).fetchdf()
    if df.empty:
        # Still write empty parquet for resume markers? Skip.
        return {"date": day.isoformat(), "rows": 0, "path": None, "skipped": False}

    norms = df["vessel_name"].map(normalize_name)
    # Expand fleet aliases
    fleet_expanded: set[str] = set()
    for n in fleet_norms:
        fleet_expanded |= aliases_for(n)

    def is_fleet(norm: str) -> bool:
        if not norm:
            return False
        if norm in fleet_expanded:
            return True
        # containment either way (avoid ultra-short false positives)
        for f in fleet_expanded:
            if len(f) < 4:
                continue
            if f in norm or (len(norm) >= 4 and norm in f):
                return True
        return False

    mask = norms.map(is_fleet)
    fleet_df = df.loc[mask].copy()
    fleet_df["vessel_name_norm"] = norms[mask].values
    fleet_df["date"] = day.isoformat()
    if fleet_df.empty:
        return {"date": day.isoformat(), "rows": 0, "path": None, "skipped": False}

    fleet_df.to_parquet(out_path, index=False)
    return {"date": day.isoformat(), "rows": int(len(fleet_df)), "path": str(out_path), "skipped": False}


def rebuild_mmsi_registry(ais_dir: Path, out_path: Path, trips_path: Path) -> pd.DataFrame:
    files = sorted(ais_dir.glob("ais_*.parquet"))
    if not files:
        return pd.DataFrame()
    con = duckdb.connect()
    glob = (ais_dir / "ais_*.parquet").as_posix()
    df = con.execute(
        f"""
        SELECT mmsi, any_value(vessel_name) AS vessel_name,
               any_value(vessel_name_norm) AS vessel_name_norm,
               any_value(call_sign) AS call_sign,
               count(*) AS n_points,
               min(base_date_time) AS first_seen,
               max(base_date_time) AS last_seen
        FROM read_parquet('{glob}')
        GROUP BY mmsi
        ORDER BY n_points DESC
        """
    ).fetchdf()

    # Attach fish-report boat names by normalized match.
    fleet = {}
    if trips_path.exists():
        with trips_path.open() as f:
            for line in f:
                row = json.loads(line)
                for alias in aliases_for(row.get("boat_name", "")):
                    fleet.setdefault(alias, set()).add(row["boat_name"])

    matched = []
    for _, r in df.iterrows():
        norm = r["vessel_name_norm"] or normalize_name(r["vessel_name"])
        report_names = sorted(fleet.get(norm, []))
        if not report_names:
            for k, names in fleet.items():
                if len(k) >= 4 and (k in norm or norm in k):
                    report_names = sorted(names)
                    break
        matched.append(
            {
                "mmsi": int(r["mmsi"]),
                "ais_vessel_name": r["vessel_name"],
                "vessel_name_norm": norm,
                "call_sign": r["call_sign"],
                "report_boat_names": report_names,
                "n_points": int(r["n_points"]),
                "first_seen": str(r["first_seen"]),
                "last_seen": str(r["last_seen"]),
                "match_confidence": "high"
                if report_names and normalize_name(report_names[0]) == norm
                else ("medium" if report_names else "unmatched_ais_only"),
            }
        )
    reg = pd.DataFrame(matched)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    reg.to_json(out_path, orient="records", indent=2)
    return reg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=PILOT_AIS_START)
    ap.add_argument("--end", default=PILOT_AIS_END)
    ap.add_argument("--trips", type=Path, default=DATA_RAW / "fish_reports" / "trips.jsonl")
    ap.add_argument("--out-dir", type=Path, default=DATA_PROCESSED / "ais_daily")
    args = ap.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    fleet_norms = load_fleet_names(args.trips)
    if not fleet_norms:
        print("No fleet names found in trips file; refusing to extract all SoCal traffic.", file=sys.stderr)
        sys.exit(2)
    print(f"Fleet normalized names: {len(fleet_norms)}")

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")

    summary = []
    for day in daterange(start, end):
        info = extract_day(con, day, fleet_norms, args.out_dir)
        summary.append(info)
        print(f"{info['date']}: rows={info['rows']} skipped={info.get('skipped')}")

    reg_path = DATA_PROCESSED / "vessel_mmsi_registry.json"
    rebuild_mmsi_registry(args.out_dir, reg_path, args.trips)
    summary_path = DATA_PROCESSED / "ais_extract_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"Registry -> {reg_path}")
    print(f"Summary -> {summary_path}")


if __name__ == "__main__":
    main()
