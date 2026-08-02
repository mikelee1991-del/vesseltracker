# LA Sportfishing Vessel Tracker (pilot)

Cloud-hosted map + pipeline that joins **SoCal fish-report dock totals** with **free NOAA Marine Cadastre AIS** for LA-basin sportfishing boats.

Live page (GitHub Pages): `docs/index.html` → enable Pages from `/docs`.

## What this does

1. Scrapes daily boat fish counts from [socalfishreports.com](https://www.socalfishreports.com/dock_totals/boats.php) for Redondo Beach, San Pedro, Long Beach, Marina Del Rey, and Newport Beach.
2. Computes **fish per person** and **species per person** directly from report totals (kept fish ÷ anglers).
3. Pulls Marine Cadastre daily AIS (1-minute NAIS sample) for matching vessels in a SoCal bbox.
4. Detects **offshore stationary stops** (low SOG, min duration, outside home-dock radii) and measures dwell time.
5. Displays results on a **NOAA BlueTopo** map with a day control.

### Explicit non-goals (for now)

- **No fabricated data.**
- **Catch counts are not split across fishing stops.** Trip totals stay at voyage level. Location productivity will be estimated later by cross-vessel statistics (see `FEEDBACK.md`).

## AIS source note

- Source: NOAA Marine Cadastre bulk daily CSV (`.csv.zst`), 1-minute sample of USCG NAIS.
- Free, no API key required for this feed.
- As of **2026-08-02**, the bulk daily feed used here is available through **2025-12-31**. 2026 days are not in that feed yet.
- Pilot AIS extract defaults to **2025-08** (scalable scripts accept any range within available files).
- No API keys needed for this path. If you later want denser-than-1-minute AIS from another free source, we can evaluate it.

### Pilot data currently in-repo

| Dataset | Coverage | Count |
|---------|----------|------:|
| Fish-report trips | 2025-01-01 → 2025-12-31 | 3,615 |
| Matched charter MMSIs | allowlisted | 17 |
| Offshore AIS stops | 2025-08 | 416 |
| Report boats with no AIS name match in Aug extract | — | see `FEEDBACK.md` |

## Pipeline

```bash
python3 -m pip install -r requirements.txt

# Full pilot (year of reports + August 2025 AIS)
python3 scripts/run_pilot.py

# Or stepwise:
python3 scripts/scrape_fish_reports.py --start 2025-01-01 --end 2025-12-31
python3 scripts/extract_ais.py --start 2025-08-01 --end 2025-08-31
python3 scripts/detect_stops.py
python3 scripts/build_map_data.py
```

Outputs:

| Path | Purpose |
|------|---------|
| `data/raw/fish_reports/trips.jsonl` | Scraped dock totals |
| `data/processed/ais_daily/*.parquet` | Filtered AIS for fleet |
| `data/processed/vessel_mmsi_registry.json` | Boat name ↔ MMSI matches |
| `data/processed/offshore_stops.json` | Detected fishing stops |
| `docs/data/meta.json` + `docs/data/days/*.json` | GitHub Pages payloads |

## Scalability

- AIS is processed **one day at a time** via DuckDB streaming over HTTP; national raw files are not retained.
- Map data is **partitioned by day** (`docs/data/days/YYYY-MM-DD.json`) so the browser loads one day at a time.
- Expanding to multiple years means widening `--start/--end` and optionally moving `data/processed/ais_daily` to object storage / GitHub Releases.

## Corrections

Use [`FEEDBACK.md`](FEEDBACK.md) to correct MMSI matches, dock radii, stop thresholds, or port inclusion. Re-run the affected pipeline steps after edits.
