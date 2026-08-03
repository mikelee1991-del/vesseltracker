"""Nominal trip duration from socalfishreports trip_type labels.

Dock totals do not include clock-in/out times. Trip products are sold as
1/2 day, 3/4 day, full day, overnight, multi-day, etc. We map those labels to
approximate **scheduled trip hours** so catch can be compared as
fish/person/hour across unequal trip lengths.

AIS offshore-stop dwell is a different signal (time hung on a pin) and should
not be the primary trip catch-rate denominator: it misses trolling, only
exists for matched MMSIs, and is sensitive to stop thresholds.
"""

from __future__ import annotations

import re

# Approximate scheduled hours for LA-basin sportfishing products.
# Tunable via FEEDBACK.md if landings publish different schedules.
HALF_DAY_H = 5.0
THREE_QUARTER_H = 8.0
FULL_DAY_H = 11.0
OVERNIGHT_H = 18.0  # evening depart → next-day return product
DAY_FISHING_H = 12.0  # per calendar fishing day on multi-day trips

# Non-fishing or unknown products → no rate.
_NULL_TYPES = {
    "whale watch",
    "whale watch am",
    "whale watch pm",
    "1/2 day whale watch",
}


def normalize_trip_type(trip_type: str | None) -> str:
    return re.sub(r"\s+", " ", (trip_type or "").strip().lower())


def nominal_trip_hours(trip_type: str | None) -> float | None:
    """Return approximate scheduled hours for a dock-total trip_type, or None."""
    tt = normalize_trip_type(trip_type)
    if not tt or tt in _NULL_TYPES:
        return None

    # Explicit multi-day fractions first.
    m = re.match(r"^(\d+(?:\.\d+)?)\s*day\b", tt)
    if m:
        days = float(m.group(1))
        if days <= 0:
            return None
        if days == 0.5 or abs(days - 0.5) < 1e-6:
            return HALF_DAY_H
        if abs(days - 0.75) < 1e-6:
            return THREE_QUARTER_H
        if abs(days - 1.0) < 1e-6:
            return FULL_DAY_H
        if abs(days - 1.25) < 1e-6:
            return FULL_DAY_H + HALF_DAY_H * 0.5
        if abs(days - 1.5) < 1e-6 or abs(days - 1.75) < 1e-6:
            return OVERNIGHT_H if days <= 1.5 else OVERNIGHT_H + HALF_DAY_H
        # 2+ day trips: ~12 fishing hours per day (steam/sleep excluded coarsely).
        return days * DAY_FISHING_H

    if "overnight" in tt:
        return OVERNIGHT_H
    if tt.startswith("3/4") or "3/4 day" in tt:
        return THREE_QUARTER_H
    if tt.startswith("1/2") or tt in {"am", "pm", "twilight"} or "twilight" in tt:
        return HALF_DAY_H
    if tt.startswith("full day") or tt == "full day":
        return FULL_DAY_H
    # Specialty local bottomfish / lobster trips are usually ~3/4–full day.
    if tt in {"lobster", "halibut", "local", "coastal", "extended 1/2 day"}:
        return THREE_QUARTER_H if tt != "extended 1/2 day" else HALF_DAY_H + 1.0
    if "santa catalina" in tt:
        return FULL_DAY_H
    return None


def fish_per_person_hour(
    fish_per_person: float | None,
    trip_type: str | None,
) -> float | None:
    hours = nominal_trip_hours(trip_type)
    if fish_per_person is None or hours is None or hours <= 0:
        return None
    return fish_per_person / hours


def species_per_person_hour(
    species_per_person: dict[str, float] | None,
    trip_type: str | None,
) -> dict[str, float]:
    hours = nominal_trip_hours(trip_type)
    if not species_per_person or hours is None or hours <= 0:
        return {}
    return {k: (v / hours) for k, v in species_per_person.items() if v is not None}
