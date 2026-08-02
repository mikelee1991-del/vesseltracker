# Feedback / error-correction log

Feed this file back to the agent (or edit it yourself) to correct assumptions.
Only include **verified** corrections — do not invent MMSIs or catches.

## Open questions / known limitations

1. **AIS availability:** Marine Cadastre bulk daily AIS used by this repo currently ends at `2025-12-31`. Confirm if you have another free source for 2026+ high-frequency AIS.
2. **Day join timezone:** AIS timestamps are UTC; fish reports are calendar days (likely Pacific). Near-midnight trips may join to the wrong local day.
3. **Name ↔ MMSI matching:** Automated from AIS `vessel_name` vs report boat names. Ambiguous names need manual confirmation below.
4. **Catch attribution:** Per your decision, trip totals are **not** split across stops yet.

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

Still unmatched after name search + trip-day correlation + dock-departure fingerprinting
(2026-08-02). **Do not invent mappings** — dock heuristics produced wrong vessel names
(e.g. Pursuit↛SEANA C).

| Report boat | Notes |
|-------------|--------|
| Pursuit | No AIS name hit on trip days in SoCal NAIS |
| Betty-O | No trustworthy MDR match; VesselFinder has no BETTY-O |
| Ghost | `GHOST DANCER` (366892030) **absent** on Ghost trip days |
| Amigo, Aggressor, Blackfish, Sport King, Pride, Gail Force, Pescador, MarDiosa, Patriot (Newport), Truline, Navegante, Betty-G, Apollo | No verified identity |

Likely causes: no AIS / Class B not in this feed / different broadcast name / land-based NAIS gaps.

If you know an MMSI or AIS name, add it under **Confirmed MMSI mappings** above.

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

## Free-form notes

-
