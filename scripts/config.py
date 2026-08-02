"""Shared configuration for the LA sportfishing AIS + fish-report pilot."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
DOCS_DATA = ROOT / "docs" / "data"

# Target landings / city sections on socalfishreports.com dock totals.
# Prefer Redondo / San Pedro; include nearby LA-basin ports.
TARGET_CITIES = {
    "Redondo Beach",
    "San Pedro",
    "Long Beach",
    "Marina Del Rey",
    "Newport Beach",
}

# SoCal coastal bbox used when filtering Marine Cadastre AIS (WGS84).
AIS_BBOX = {
    "min_lon": -119.05,
    "max_lon": -117.55,
    "min_lat": 33.35,
    "max_lat": 34.15,
}

# Home-dock exclusion zones (approx centers). Stops inside these are not
# treated as fishing locations.
HOME_DOCKS = [
    {"name": "Redondo Beach Sportfishing", "lat": 33.8455, "lon": -118.3930, "radius_m": 800},
    {"name": "22nd Street Landing (San Pedro)", "lat": 33.7235, "lon": -118.2765, "radius_m": 900},
    {"name": "LA Waterfront / San Pedro", "lat": 33.7390, "lon": -118.2780, "radius_m": 900},
    {"name": "Long Beach Sportfishing", "lat": 33.7605, "lon": -118.1955, "radius_m": 900},
    {"name": "Pierpoint Landing (Long Beach)", "lat": 33.7570, "lon": -118.1900, "radius_m": 800},
    {"name": "Marina Del Rey Sportfishing", "lat": 33.9735, "lon": -118.4485, "radius_m": 900},
    {"name": "Newport Landing / Davey's Locker", "lat": 33.6030, "lon": -117.9285, "radius_m": 900},
]

# Stop detection (pilot defaults; tune via FEEDBACK.md).
STOP_MAX_SOG_KN = 0.8
STOP_MIN_DURATION_MIN = 20
STOP_GAP_MIN = 30  # merge gap between low-speed segments
STOP_CLUSTER_RADIUS_M = 250

# Marine Cadastre 2025 daily AIS (1-minute sample of NAIS broadcasts).
# Note: as of 2026-08-02, free bulk AIS appears published through 2025-12-31.
AIS_BASE_URL = "https://noaaocm.blob.core.windows.net/ais/csv2/csv2025"
AIS_FILENAME = "ais-{date}.csv.zst"  # date = YYYY-MM-DD

FISH_REPORT_URL = "https://www.socalfishreports.com/dock_totals/boats.php"
FISH_REPORT_SOURCE = "https://www.socalfishreports.com/"

# Pilot date windows (real data only; no fabrication).
# Fish reports: calendar year overlapping available AIS.
PILOT_REPORT_START = "2025-01-01"
PILOT_REPORT_END = "2025-12-31"
# AIS extract for first ship: peak summer month (script accepts wider ranges).
PILOT_AIS_START = "2025-08-01"
PILOT_AIS_END = "2025-08-31"

USER_AGENT = "vesseltracker-research/0.1 (+https://github.com/mikelee1991-del/vesseltracker; educational research)"
REQUEST_SLEEP_SEC = 0.35
