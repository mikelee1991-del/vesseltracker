# LA Sportfishing Vessel Tracker (pilot)

Cloud-hosted map + pipeline that joins **SoCal fish-report dock totals** with **free NOAA Marine Cadastre AIS** for LA-basin sportfishing boats.

Live page (GitHub Pages): `docs/index.html` → enable Pages from `/docs`.

## Viewing the map

**Live preview (no Pages setup required):**
https://cdn.jsdelivr.net/gh/mikelee1991-del/vesseltracker@main/docs/

**GitHub Pages (live):**
https://mikelee1991-del.github.io/vesseltracker/

Cloud-agent GitHub tokens can **push to `main`** but cannot enable the Pages site
(`pages: write` create-site is blocked as “Resource not accessible by integration”).
One-time owner action: repo **Settings → Pages → Source: GitHub Actions**, then
re-run the `Deploy GitHub Pages` workflow (or push any commit to `main`).


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
- As of **2026-08-03**, bulk daily CSV years **2015–2025** are published (`csv2015`…`csv2025`). **`csv2026` is not out yet.**
- Default extract window: **2015-01-01 → 2025-12-31** (all CSV years), filtered to the SoCal bbox + fleet names/MMSIs.
- Fish-report scrape default: **2005-01-01 → latest** (site archive); join/crosscheck is strongest where AIS overlaps (2015+).
- No API keys needed for this path. Optional live forward archive: `scripts/collect_aisstream.py`.

### Pilot data currently in-repo

| Dataset | Coverage | Notes |
|---------|----------|------|
| Fish-report trips | 2005 → 2026 YTD (target cities) | Growing as scrape completes |
| Marine Cadastre AIS extract | 2015 → 2025 | Fleet-filtered parquet under `data/processed/ais_daily/` |
| Matched charter MMSIs | allowlisted | see `scripts/config.py` / `FEEDBACK.md` |

## Pipeline

```bash
python3 -m pip install -r requirements.txt

# Full archive crosscheck (all Cadastre CSV years + all fish reports)
python3 scripts/run_pilot.py

# Or stepwise:
python3 scripts/scrape_fish_reports.py --start 2005-01-01 --end 2026-08-02 --workers 4
python3 scripts/extract_ais.py --start 2015-01-01 --end 2025-12-31 --workers 6
python3 scripts/refine_registry.py
python3 scripts/detect_stops.py
python3 scripts/build_map_data.py
```

Outputs:

| Path | Purpose |
|------|---------|
| `data/raw/fish_reports/by_year/trips_YYYY.jsonl` | Scraped dock totals (yearly shards) |
| `data/processed/ais_daily/*.parquet` | Filtered AIS for fleet (local/regenerable; gitignored) |
| `data/processed/vessel_mmsi_registry.json` | Boat name ↔ MMSI matches |
| `data/processed/offshore_stops.json` | Detected fishing stops |
| `docs/data/meta.json` + `docs/data/days/*.json` | GitHub Pages payloads |

## Scalability

- AIS is processed **one day at a time** via DuckDB streaming over HTTP; national raw files are not retained.
- Map data is **partitioned by day** (`docs/data/days/YYYY-MM-DD.json`) so the browser loads one day at a time.
- Expanding to multiple years means widening `--start/--end` and optionally moving `data/processed/ais_daily` to object storage / GitHub Releases.

## Corrections

Use [`FEEDBACK.md`](FEEDBACK.md) to correct MMSI matches, dock radii, stop thresholds, or port inclusion. Re-run the affected pipeline steps after edits.
