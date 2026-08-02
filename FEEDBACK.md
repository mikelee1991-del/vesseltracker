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

## Boats in reports with no AIS name match in Aug 2025 extract

Aggressor, Amigo, Apollo, Betty-G, Betty-O, Blackfish, Gail Force, Ghost, MarDiosa, Navegante, Pescador, Pride, Pursuit, Sport King, Truline.

These may not broadcast, may use a different AIS name, or may be outside the SoCal land-based NAIS coverage used by Marine Cadastre.

## Dock exclusion radius adjustments

| Dock | Current radius_m | Suggested radius_m | Why |
|------|------------------:|-------------------:|-----|
| | | | |

## Stop-detection tuning

Current defaults in `scripts/config.py`:

- `STOP_MAX_SOG_KN = 0.8`
- `STOP_MIN_DURATION_MIN = 20`
- `STOP_GAP_MIN = 30`

Suggested changes:

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
