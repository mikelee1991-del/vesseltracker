#!/usr/bin/env python3
"""Scrape daily boat fish counts from socalfishreports.com for target cities."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from config import (  # noqa: E402
    DATA_RAW,
    FISH_REPORT_URL,
    PILOT_REPORT_END,
    PILOT_REPORT_START,
    REQUEST_SLEEP_SEC,
    TARGET_CITIES,
    USER_AGENT,
)

ANGLERS_RE = re.compile(r"(\d+)\s*Anglers?", re.I)
COUNT_RE = re.compile(
    r"(\d+)\s+([A-Za-z][A-Za-z0-9'/\- ]+?)(?=(?:,\s*\d+\s+[A-Za-z])|$)",
    re.I,
)
RELEASED_RE = re.compile(r"\breleased\b", re.I)
UP_TO_RE = re.compile(r"\s*\(up to[^)]*\)", re.I)


def daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def parse_species(text: str) -> list[dict]:
    text = UP_TO_RE.sub("", (text or "").strip())
    if not text:
        return []
    out = []
    for m in COUNT_RE.finditer(text):
        count = int(m.group(1))
        name = m.group(2).strip(" ,")
        released = bool(RELEASED_RE.search(name))
        name = RELEASED_RE.sub("", name).strip(" ,")
        if not name:
            continue
        out.append({"species": name, "count": count, "released": released})
    return out


def parse_day_html(html: str, day: date) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    rows_out: list[dict] = []
    for panel in soup.select("div.panel"):
        h2 = panel.find("h2")
        if not h2:
            continue
        title = h2.get_text(" ", strip=True)
        if not title.endswith("Fish Counts"):
            continue
        city = title.replace("Fish Counts", "").strip()
        if city not in TARGET_CITIES:
            continue
        for tr in panel.select("table tbody tr"):
            tds = tr.find_all("td")
            if len(tds) < 3:
                continue
            boat_td, trip_td, totals_td = tds[0], tds[1], tds[2]
            boat_link = boat_td.find("a")
            boat_name = boat_link.get_text(strip=True) if boat_link else ""
            boat_href = boat_link.get("href") if boat_link else None
            landing_link = None
            for a in boat_td.find_all("a"):
                href = a.get("href") or ""
                if "/landings/" in href:
                    landing_link = a
                    break
            landing_name = landing_link.get_text(strip=True) if landing_link else ""
            city_line = ""
            bits = list(boat_td.stripped_strings)
            if bits:
                city_line = bits[-1]
            trip_text = trip_td.get_text("\n", strip=True)
            anglers_m = ANGLERS_RE.search(trip_text)
            anglers = int(anglers_m.group(1)) if anglers_m else None
            trip_lines = [ln.strip() for ln in trip_text.split("\n") if ln.strip()]
            trip_type = trip_lines[1] if len(trip_lines) > 1 else (trip_lines[0] if trip_lines else "")
            if anglers_m and trip_type.startswith(anglers_m.group(0)):
                trip_type = trip_type[len(anglers_m.group(0)) :].strip()
            totals_text = totals_td.get_text(" ", strip=True)
            species = parse_species(totals_text)
            kept = [s for s in species if not s["released"]]
            total_kept = sum(s["count"] for s in kept)
            fish_per_person = (total_kept / anglers) if anglers and anglers > 0 else None
            species_per_person = {
                s["species"]: (s["count"] / anglers) for s in kept if anglers and anglers > 0
            }
            rows_out.append(
                {
                    "date": day.isoformat(),
                    "city": city,
                    "boat_name": boat_name,
                    "boat_url": boat_href,
                    "landing_name": landing_name,
                    "city_line": city_line,
                    "anglers": anglers,
                    "trip_type": trip_type,
                    "dock_totals_raw": totals_text,
                    "species": species,
                    "total_fish_kept": total_kept,
                    "fish_per_person": fish_per_person,
                    "species_per_person": species_per_person,
                    "source": FISH_REPORT_URL + f"?date={day.isoformat()}",
                }
            )
    return rows_out


def fetch_day(session: requests.Session, day: date) -> list[dict]:
    url = f"{FISH_REPORT_URL}?date={day.isoformat()}"
    r = session.get(url, timeout=60)
    r.raise_for_status()
    return parse_day_html(r.text, day)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=PILOT_REPORT_START)
    ap.add_argument("--end", default=PILOT_REPORT_END)
    ap.add_argument("--out", type=Path, default=DATA_RAW / "fish_reports" / "trips.jsonl")
    args = ap.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html"})

    # Resume support: skip dates already present.
    seen_dates: set[str] = set()
    if args.out.exists():
        with args.out.open() as f:
            for line in f:
                try:
                    seen_dates.add(json.loads(line)["date"])
                except Exception:
                    continue

    total_rows = 0
    with args.out.open("a") as out:
        for day in daterange(start, end):
            if day.isoformat() in seen_dates:
                continue
            try:
                rows = fetch_day(session, day)
            except Exception as e:
                print(f"[warn] {day}: {e}", file=sys.stderr)
                time.sleep(REQUEST_SLEEP_SEC * 3)
                continue
            for row in rows:
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                total_rows += 1
            out.flush()
            print(f"{day.isoformat()}: {len(rows)} trips")
            time.sleep(REQUEST_SLEEP_SEC)

    print(f"Wrote/updated {args.out} (+{total_rows} new rows)")


if __name__ == "__main__":
    main()
