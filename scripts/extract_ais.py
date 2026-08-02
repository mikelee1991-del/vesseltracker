#!/usr/bin/env python3
"""
Extract Marine Cadastre daily AIS broadcasts for LA-area charter vessels.

Uses DuckDB + httpfs to stream-filter remote .csv.zst files (1-minute NAIS
sample). Only rows matching the SoCal bbox and strict fleet name/alias filters
are kept. Designed to scale day-by-day without retaining national raw files.
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
    VESSEL_ALIASES,
)

NAME_NORMALIZE_RE = re.compile(r"[^A-Z0-9]+")


def daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def normalize_name(name: str) -> str:
    return NAME_NORMALIZE_RE.sub("", (name or "").upper())


def build_accepted_names(trips_path: Path) -> dict[str, str]:
    """Map accepted AIS normalized names -> canonical report boat name.

    Matching is exact on normalized strings, plus explicit aliases in
    config.VESSEL_ALIASES and unambiguous parenthetical/base shortenings.
    Substring containment is intentionally NOT used (avoids SWEET FREEDOM→Freedom).
    """
    accepted: dict[str, str] = {}
    if not trips_path.exists():
        return accepted

    report_names: set[str] = set()
    with trips_path.open() as f:
        for line in f:
            bn = json.loads(line).get("boat_name") or ""
            if not bn:
                continue
            report_names.add(bn)
            accepted[normalize_name(bn)] = bn

    for ais_norm, report_name in VESSEL_ALIASES.items():
        if report_name in report_names:
            accepted[normalize_name(ais_norm)] = report_name

    bases: dict[str, list[str]] = {}
    for bn in report_names:
        n = normalize_name(bn)
        for suf in ("NEWPORT", "VENTURA", "MB", "LB", "SPECIAL"):
            if n.endswith(suf) and len(n) > len(suf) + 2:
                bases.setdefault(n[: -len(suf)], []).append(bn)
    for base, names in bases.items():
        uniq = sorted(set(names))
        if len(uniq) == 1 and base not in accepted:
            accepted[base] = uniq[0]
    return accepted


def extract_day(
    con: duckdb.DuckDBPyConnection,
    day: date,
    accepted: dict[str, str],
    out_dir: Path,
    force: bool,
) -> dict:
    out_path = out_dir / f"ais_{day.isoformat()}.parquet"
    if out_path.exists() and not force:
        n = con.execute(f"SELECT count(*) FROM read_parquet('{out_path.as_posix()}')").fetchone()[0]
        return {"date": day.isoformat(), "rows": int(n), "path": str(out_path), "skipped": True}

    url = f"{AIS_BASE_URL}/{AIS_FILENAME.format(date=day.isoformat())}"
    bbox = AIS_BBOX
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
        if out_path.exists():
            out_path.unlink()
        return {"date": day.isoformat(), "rows": 0, "path": None, "skipped": False}

    norms = df["vessel_name"].map(normalize_name)
    mask = norms.isin(set(accepted.keys()))
    fleet_df = df.loc[mask].copy()
    fleet_df["vessel_name_norm"] = norms[mask].values
    fleet_df["report_boat_name"] = fleet_df["vessel_name_norm"].map(accepted)
    fleet_df["date"] = day.isoformat()
    if fleet_df.empty:
        if out_path.exists():
            out_path.unlink()
        return {"date": day.isoformat(), "rows": 0, "path": None, "skipped": False}

    fleet_df.to_parquet(out_path, index=False)
    return {"date": day.isoformat(), "rows": int(len(fleet_df)), "path": str(out_path), "skipped": False}


def rebuild_mmsi_registry(ais_dir: Path, out_path: Path, accepted: dict[str, str]) -> pd.DataFrame:
    files = sorted(ais_dir.glob("ais_*.parquet"))
    if not files:
        return pd.DataFrame()
    con = duckdb.connect()
    glob = (ais_dir / "ais_*.parquet").as_posix()
    df = con.execute(
        f"""
        SELECT mmsi,
               any_value(vessel_name) AS vessel_name,
               any_value(vessel_name_norm) AS vessel_name_norm,
               any_value(report_boat_name) AS report_boat_name,
               any_value(call_sign) AS call_sign,
               count(*) AS n_points,
               min(base_date_time) AS first_seen,
               max(base_date_time) AS last_seen
        FROM read_parquet('{glob}')
        GROUP BY mmsi
        ORDER BY n_points DESC
        """
    ).fetchdf()

    matched = []
    for _, r in df.iterrows():
        norm = r["vessel_name_norm"] or normalize_name(r["vessel_name"])
        report_name = r["report_boat_name"] or accepted.get(norm)
        matched.append(
            {
                "mmsi": int(r["mmsi"]),
                "ais_vessel_name": r["vessel_name"],
                "vessel_name_norm": norm,
                "call_sign": r["call_sign"],
                "report_boat_names": [report_name] if report_name else [],
                "n_points": int(r["n_points"]),
                "first_seen": str(r["first_seen"]),
                "last_seen": str(r["last_seen"]),
                "match_confidence": "high" if report_name else "unmatched_ais_only",
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
    ap.add_argument("--force", action="store_true", help="Re-download/filter even if parquet exists")
    args = ap.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    accepted = build_accepted_names(args.trips)
    if not accepted:
        print("No fleet names found in trips file; refusing to extract all SoCal traffic.", file=sys.stderr)
        sys.exit(2)
    print(f"Accepted AIS name keys: {len(accepted)}")

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")

    summary = []
    for day in daterange(start, end):
        info = extract_day(con, day, accepted, args.out_dir, force=args.force)
        summary.append(info)
        print(f"{info['date']}: rows={info['rows']} skipped={info.get('skipped')}")

    reg_path = DATA_PROCESSED / "vessel_mmsi_registry.json"
    rebuild_mmsi_registry(args.out_dir, reg_path, accepted)
    summary_path = DATA_PROCESSED / "ais_extract_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"Registry -> {reg_path}")
    print(f"Summary -> {summary_path}")


if __name__ == "__main__":
    main()
