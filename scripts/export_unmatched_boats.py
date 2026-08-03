#!/usr/bin/env python3
"""Export unmatched report boats for the human MMSI verification tool."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from config import (  # noqa: E402
    DATA_PROCESSED,
    DATA_RAW,
    DOCS_DATA,
    FOCUS_MATCH_CITIES,
    MMSI_ALLOWLIST,
    MMSI_DENYLIST,
    MMSI_TO_REPORT_BOAT,
    VESSEL_ALIASES,
)
from extract_ais import build_accepted_names, normalize_name  # noqa: E402
from trips_io import load_trips  # noqa: E402


def high_confidence_names(registry: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in registry:
        if r.get("match_confidence") not in ("high", "high_secondary"):
            continue
        mmsi = int(r["mmsi"])
        for n in r.get("report_boat_names") or []:
            out[normalize_name(n)] = mmsi
        if r.get("ais_vessel_name"):
            out[normalize_name(r["ais_vessel_name"])] = mmsi
    for mmsi, boat in MMSI_TO_REPORT_BOAT.items():
        out[normalize_name(boat)] = int(mmsi)
    for alias, boat in VESSEL_ALIASES.items():
        if normalize_name(boat) in out:
            out[normalize_name(alias)] = out[normalize_name(boat)]
    return out


def lookup_links(boat: str) -> dict[str, str]:
    q = quote_plus(boat)
    return {
        "marinetraffic": f"https://www.marinetraffic.com/en/ais/index/search/all?keyword={q}",
        "vesselfinder": f"https://www.vesselfinder.com/vessels?name={q}",
    }


def load_search_hints(path: Path) -> dict[str, list[dict]]:
    if not path.exists():
        return {}
    try:
        rows = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    by_boat: dict[str, list[dict]] = defaultdict(list)
    seen: set[tuple[str, int]] = set()
    for r in rows:
        boat = r.get("report_boat") or ""
        mmsi = int(r.get("mmsi") or 0)
        if not boat or not mmsi:
            continue
        key = (boat, mmsi)
        if key in seen:
            continue
        seen.add(key)
        by_boat[boat].append(
            {
                "mmsi": mmsi,
                "ais_name": r.get("vessel_name"),
                "length_m": r.get("length"),
                "vessel_type": r.get("vessel_type"),
                "call_sign": r.get("call_sign"),
                "sample_day": r.get("day"),
                "denied": mmsi in MMSI_DENYLIST,
                "allowlisted": mmsi in MMSI_ALLOWLIST,
                "note": (
                    "Already denied — do not confirm"
                    if mmsi in MMSI_DENYLIST
                    else "Name-search candidate only — verify before confirming"
                ),
            }
        )
    return dict(by_boat)


def build_payload(trips: list[dict], registry: list[dict], hints: dict[str, list[dict]]) -> dict:
    matched_names = high_confidence_names(registry)
    stats: dict[str, dict] = {}

    for t in trips:
        boat = t.get("boat_name") or "?"
        city = t.get("city") or ""
        landing = t.get("landing_name") or ""
        rec = stats.setdefault(
            boat,
            {
                "report_boat": boat,
                "n_trips": 0,
                "cities": Counter(),
                "landings": Counter(),
            },
        )
        rec["n_trips"] += 1
        if city:
            rec["cities"][city] += 1
        if landing:
            rec["landings"][landing] += 1

    focus_cities_l = {c.lower() for c in FOCUS_MATCH_CITIES}
    boats_out = []
    matched_focus = []
    for boat, rec in stats.items():
        nkey = normalize_name(boat)
        alias_key = normalize_name(VESSEL_ALIASES.get(nkey, boat))
        mmsi = matched_names.get(nkey) or matched_names.get(alias_key)
        cities = [c for c, _ in rec["cities"].most_common()]
        landings = [{"name": n, "n": c} for n, c in rec["landings"].most_common()]
        in_focus = any(c.lower() in focus_cities_l for c in cities) or any(
            any(fc in (landing.get("name") or "").lower() for fc in ("redondo", "san pedro", "22nd"))
            for landing in landings
        )
        row = {
            "report_boat": boat,
            "n_trips": rec["n_trips"],
            "cities": cities,
            "landings": landings,
            "priority": "focus" if in_focus else "other",
            "lookup": lookup_links(boat),
            "search_hints": hints.get(boat, []),
        }
        if mmsi:
            row["status"] = "matched"
            row["mmsi"] = int(mmsi)
            if in_focus:
                matched_focus.append(row)
        else:
            row["status"] = "unmatched"
            boats_out.append(row)

    boats_out.sort(key=lambda r: (-(r["priority"] == "focus"), -r["n_trips"], r["report_boat"]))
    matched_focus.sort(key=lambda r: (-r["n_trips"], r["report_boat"]))

    focus_unmatched = [b for b in boats_out if b["priority"] == "focus"]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "focus_ports": sorted(FOCUS_MATCH_CITIES),
        "instructions": (
            "Confirm an MMSI only if you know it is that charter’s AIS identity "
            "(hull, FCC/USCG docs, MarineTraffic track that matches trip days, "
            "or captain/landing confirmation). Include the AIS broadcast name if "
            "it differs from the dock-total name. Download JSON and send it back "
            "or run scripts/apply_mmsi_feedback.py."
        ),
        "stats": {
            "n_unmatched_boats": len(boats_out),
            "n_unmatched_focus_boats": len(focus_unmatched),
            "n_unmatched_focus_trips": sum(b["n_trips"] for b in focus_unmatched),
            "n_matched_focus_boats": len(matched_focus),
        },
        "unmatched": boats_out,
        "matched_focus": matched_focus,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trips", type=Path, default=DATA_RAW / "fish_reports" / "by_year")
    ap.add_argument("--registry", type=Path, default=DATA_PROCESSED / "vessel_mmsi_registry.json")
    ap.add_argument(
        "--hints",
        type=Path,
        default=DATA_PROCESSED / "mmsi_name_search.json",
        help="Optional prior name-search candidates (never auto-accept)",
    )
    ap.add_argument("--out", type=Path, default=DOCS_DATA / "unmatched_boats.json")
    args = ap.parse_args()

    trips = load_trips(args.trips)
    registry = json.loads(args.registry.read_text()) if args.registry.exists() else []
    # Touch accepted names so export stays consistent with extract aliases.
    _ = build_accepted_names(args.trips)
    hints = load_search_hints(args.hints)
    payload = build_payload(trips, registry, hints)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload["stats"], indent=2))
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
