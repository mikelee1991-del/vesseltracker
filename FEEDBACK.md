# Feedback / error-correction log

Feed this file back to the agent (or edit it yourself) to correct assumptions.
Only include **verified** corrections — do not invent MMSIs or catches.

## Open questions / known limitations

1. **AIS availability (researched 2026-08-03):** There is **no free drop-in historical
   AIS archive for US waters covering 2026 YTD** yet. Details in
   [AIS source options](#ais-source-options-2026) below. Fish reports are scraped
   through **2026-08-02**.
2. **Day join timezone:** AIS timestamps are UTC; fish reports are calendar days (likely Pacific). Near-midnight trips may join to the wrong local day.
3. **Name ↔ MMSI matching:** Automated from AIS `vessel_name` vs report boat names. Ambiguous names need manual confirmation below.
4. **Catch attribution:** Per your decision, trip totals are **not** split across stops yet.
5. **Fleet coverage:** Expanded dock totals to Dana Point (2026-08-02). Most high-volume LA boats
   without AIS (Betty-O, Pursuit, Patriot, Ghost, …) still cannot be added without a known MMSI.

## Confirmed MMSI mappings

Pilot allowlist (from AIS name + length/type/call-sign heuristics; please verify):

| Report boat name | MMSI | AIS name | Notes |
|------------------|------|----------|-------|
| Redondo Special | 366760710 | REDONDO | Alias; call sign WCD3906 |
| New Del Mar | 366855060 | NEW DEL MAR | |
| Victory | 366977270 | VICTORY | Rejected smaller recreational VICTORY |
| Freedom | 367621160 | FREEDOM | Rejected other FREEDOM MMSIs |
| Triton | 367550710 | TRITON | Rejected 538070070 yacht |
| Freelance | 366977380 | FREELANCE | |
| Western Pride | 367158550 | WESTERN PRIDE | |
| Monte Carlo | 368014440 | MONTE CARLO | |
| Native Sun | 367655460 | NATIVE SUN | |
| Enterprise | 367095040 | ENTERPRISE | |
| Eldorado | 368089620 | ELDORADO | |
| Toronado | 367169120 | TORONADO | |
| Thunderbird | 368078070 | THUNDERBIRD | |
| El Patron | 366915000 | EL PATRON | |
| Spitfire | 368269920 | SPITFIRE | Short length / type 36 — verify |
| City of Long Beach | 367034320 | CITY OF LONG BEACH | |
| Ahra-Ahn | 367038000 | AHRA-AHN | |
| Dana Pride | 366849310 | DANA PRIDE | Dana Point only — not San Pedro Pride |
| Apollo | 368370000 | APOLLO | Sparse AIS (few days in 2025) |
| Dreamer | 338068929 | DREAMER | Sparse AIS; distinct from denied 338146692 |

## Wrong automated matches (reject)

| AIS name / MMSI | Incorrectly matched report boat | Action |
|-----------------|----------------------------------|--------|
| SWEET FREEDOM / 338225409 | Freedom | Denied |
| VICTORY / 368033280 | Victory | Denied (recreational) |
| TRITON / 538070070 | Triton | Denied (yacht) |
| PATRIOT / 338424198 | Patriot (Newport) | Denied until confirmed — no high-confidence Newport AIS name found |
| DREAMER / 338146692 | Dreamer | Denied |
| DANA PRIDE / 366849310 | Pride | Denied (Dana Point boat; Pride is San Pedro) |

## Boats in reports with no verified AIS MMSI (full 2025 NAIS search)

Still unmatched after repeated name search + trip-day correlation + dock-departure
fingerprinting (2026-08-02). **Do not invent mappings** — dock heuristics produced
wrong vessel names (e.g. Pursuit↛SEANA C; Betty-O↛LEGACY/SEANA C).

These account for a large share of trips (~1,000+) but do **not** appear under their
report names in Marine Cadastre NAIS for SoCal:

| Report boat | Trips (2025) | Notes |
|-------------|-------------:|-------|
| Betty-O | 198 | No BETTY-O AIS; parked BETTY/BETTY GENE are wrong vessels |
| Patriot (Newport) | 178 | Exact PATRIOT MMSIs are MDR/Dana idle recreational craft |
| Pursuit | 132 | No charter-sized PURSUIT track on trip days |
| Ghost | 98 | `GHOST DANCER` absent on Ghost trip days |
| Aggressor | 91 | No AIS name hit |
| Blackfish | 78 | No AIS name hit |
| Amigo | 69 | No AIS name hit |
| Sport King | 67 | No AIS name hit |
| Pride (San Pedro) | 53 | DANA PRIDE / WESTERN PRIDE are other boats |
| Gail Force | 50 | GAIL-ANNE is a parked recreational craft |
| Pescador, MarDiosa, Truline, Navegante, Betty-G | few | No verified identity |

Likely causes: no AIS transceiver / Class B not in this 1-min NAIS sample / different
broadcast name / coverage gaps.

**If you know an MMSI or AIS broadcast name for any of these, use the human tool:**
[`docs/verify-mmsi.html`](docs/verify-mmsi.html) (also linked from the map). Confirm
only verified identities, download the JSON, and send it back — or run
`python3 scripts/apply_mmsi_feedback.py path/to/mmsi_human_feedback.json`.
You can also paste rows under Confirmed MMSI mappings below.

## Dock exclusion radius adjustments

| Dock | Current radius_m | Suggested radius_m | Why |
|------|------------------:|-------------------:|-----|
| | | | |

## Stop-detection tuning

Defaults in `scripts/config.py` (updated 2026-08-02 after Aug 2025 AIS review):

- `STOP_MAX_SOG_KN = 0.8`
- `STOP_MIN_DURATION_MIN = 10` (was 20)
- `STOP_GAP_MIN = 8` (was 30)

Evidence from allowlisted fleet AIS (Aug 2025):

- Median atomic offshore low-SOG dwell ~3 min; many real dwells in the 5–20 min band
- Likely spot-to-spot hops: median ~13 min transit, ~1.3 km
- Old `gap=30` glued nearby spots; old `min=20` dropped e.g. Native Sun’s ~15 min stops on 2025-08-15

## Feature / spot clustering (underwater place grouping)

Stops within `FEATURE_CLUSTER_RADIUS_FT` of a shared centroid are merged into one
map spot (centroid-bounded clustering). Default **150 ft** (~45.7 m) absorbs typical
same-pin revisit scatter for most boats; not the full width of a reef.

| Parameter | Current | Notes |
|-----------|--------:|-------|
| `FEATURE_CLUSTER_RADIUS_FT` | 150 | Tune up if same pin still splits; down if distinct pins merge |

Further suggested changes:

| Parameter | New value | Why |
|-----------|----------:|-----|
| | | |

## Ports / vessels to include or exclude

| Change | Detail |
|--------|--------|
| | |

## Location productivity (future)

Preferred approach when we resume this (do not implement until confirmed):

- [ ] Cross-vessel co-occurrence / residual model
- [ ] Presence-weighted priors without hard splitting single-trip counts
- [ ] Other: ________

## AIS source options (2026)

Checked 2026-08-03. Goal: free historical AIS points for SoCal stop detection.

| Source | Cost | Historical 2026? | Fit for this project |
|--------|------|------------------|----------------------|
| **Marine Cadastre bulk** (`csv{YYYY}/ais-*.csv.zst`) | Free | **No** — last day `2025-12-31`; no `csv2026` | Still the best US archive when published (quarterly lag). Extractor already year-aware. |
| **AccessAIS** | Free | Unclear / **service unavailable** now; UI range ends 2025-12-31 | Prefer when back online for custom SoCal clips. |
| **aisstream.io** | Free (API key) | **No** — live websocket only | **Best free forward path.** Collector: `scripts/collect_aisstream.py`. Coverage depends on their terrestrial network. |
| **AISHub** | Free if you contribute a receiver | No (≈30 min buffer) | Not usable without running our own AIS station. |
| **Global Fishing Watch API** | Free token | Events/presence to ~96h ago; **not raw 1‑min tracks** | Useful for fishing-event centroids / identity, not a Marine Cadastre substitute for sportfishing dwells. |
| MarineTraffic / Spire / Kpler | Paid | Yes | Only option for true 2026 YTD backfill today. |

**Practical plan**

1. Pull **all published Marine Cadastre daily CSV years** (`2015-01-01` → `2025-12-31`) for the SoCal fleet bbox (see `PILOT_AIS_*` in `scripts/config.py`).
2. Scrape **all available** socalfishreports dock totals for target cities (`2005-01-01` → report end) and join where AIS overlaps.
3. Start archiving live SoCal with **aisstream** (`AISSTREAM_API_KEY`) so 2026+ gaps close going forward.
4. When NOAA drops `csv2026`, pull it and prefer it over aisstream for those days.
5. 2026-01-01 → today backfill is **not freely available** as bulk points; paid AIS or waiting on NOAA.

### Full-archive pull status (2026-08-03)

| Dataset | Coverage | Count |
|---------|----------|------:|
| Fish-report trips | 2005-01-01 → 2026-08-02 | 144,545 |
| Cadastre AIS days extracted | 2015-01-01 → 2025-12-31 | 4,004 days (14 empty) |
| Offshore stops | 2015–2025 (local Pacific dates) | 129,319 |
| Feature clusters (150 ft) | — | 12,351 |
| Trips with matched offshore stops | AIS overlap years | 20,449 |
| Trips `no_mmsi` | — | 71,863 |
| Trips `outside_ais_window` | mostly 2005–2014 + 2026 | 38,698 |
| Trips `no_offshore_stop` | in AIS window, matched MMSI | 13,535 |

Notes:
- AIS parquet under `data/processed/ais_daily/` is regenerable / gitignored (too large).
- Fish reports are stored as yearly shards in `data/raw/fish_reports/by_year/`.
- Some auto-matched MMSIs (non-allowlist name collisions) still need human review via `verify-mmsi.html`.

## Free-form notes

-
