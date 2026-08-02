# Feedback / error-correction log

Feed this file back to the agent (or edit it yourself) to correct assumptions.
Only include **verified** corrections — do not invent MMSIs or catches.

## Open questions / known limitations

1. **AIS availability:** Marine Cadastre bulk daily AIS used by this repo currently ends at `2025-12-31`. Confirm if you have another free source for 2026+ high-frequency AIS.
2. **Day join timezone:** AIS timestamps are UTC; fish reports are calendar days (likely Pacific). Near-midnight trips may join to the wrong local day.
3. **Name ↔ MMSI matching:** Automated from AIS `vessel_name` vs report boat names. Ambiguous names need manual confirmation below.
4. **Catch attribution:** Per your decision, trip totals are **not** split across stops yet.

## Confirmed MMSI mappings

<!-- Add rows like:
| Report boat name | MMSI | Evidence |
| Redondo Special | 366XXXXXX | AIS name REDONDO + home dock Redondo |
-->

| Report boat name | MMSI | Evidence / notes |
|------------------|------|------------------|
| | | |

## Wrong automated matches (reject)

| AIS name / MMSI | Incorrectly matched report boat | Action |
|-----------------|----------------------------------|--------|
| | | Remove / rematch |

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
