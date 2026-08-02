#!/usr/bin/env python3
"""Apply human MMSI confirmations/rejections from the verify-mmsi tool.

Reads a JSON file downloaded from docs/verify-mmsi.html and updates:
  - scripts/config.py  (MMSI_ALLOWLIST, MMSI_DENYLIST, MMSI_TO_REPORT_BOAT, aliases)
  - FEEDBACK.md        (Confirmed / Wrong tables)

Does not invent values — only applies rows present in the feedback file.
Re-run extract_ais / refine_registry / detect_stops / build_map_data after applying
so new MMSIs appear on the map (allowlisted MMSIs are pulled even when AIS name differs).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "scripts" / "config.py"
FEEDBACK_PATH = ROOT / "FEEDBACK.md"


def normalize_name(name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", (name or "").upper())


def load_feedback(path: Path) -> dict:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise SystemExit("Feedback file must be a JSON object")
    return data


def upsert_config_set(text: str, const_name: str, values: dict[int, str]) -> str:
    """Replace or insert integer members inside a `{ ... }` set/dict const."""
    pattern = rf"({const_name}\s*=\s*\{{)(.*?)(\n\}})"
    m = re.search(pattern, text, flags=re.S)
    if not m:
        raise SystemExit(f"Could not find {const_name} in config.py")
    body = m.group(2)
    for mmsi, comment in sorted(values.items()):
        line_re = re.compile(rf"^\s*{mmsi}\s*,.*$", re.M)
        new_line = f"    {mmsi},  # {comment}"
        if line_re.search(body):
            body = line_re.sub(new_line, body)
        else:
            body = body.rstrip() + f"\n{new_line}\n"
    return text[: m.start()] + m.group(1) + body + m.group(3) + text[m.end() :]


def upsert_config_dict(text: str, const_name: str, values: dict[int, str]) -> str:
    pattern = rf"({const_name}\s*=\s*\{{)(.*?)(\n\}})"
    m = re.search(pattern, text, flags=re.S)
    if not m:
        raise SystemExit(f"Could not find {const_name} in config.py")
    body = m.group(2)
    for mmsi, boat in sorted(values.items(), key=lambda kv: kv[1]):
        line_re = re.compile(rf"^\s*{mmsi}\s*:\s*.*$", re.M)
        new_line = f'    {mmsi}: "{boat}",'
        if line_re.search(body):
            body = line_re.sub(new_line, body)
        else:
            body = body.rstrip() + f"\n{new_line}\n"
    return text[: m.start()] + m.group(1) + body + m.group(3) + text[m.end() :]


def upsert_alias(text: str, ais_name: str, report_boat: str) -> str:
    key = normalize_name(ais_name)
    if not key or key == normalize_name(report_boat):
        return text
    pattern = r"(VESSEL_ALIASES\s*=\s*\{)(.*?)(\n\})"
    m = re.search(pattern, text, flags=re.S)
    if not m:
        raise SystemExit("Could not find VESSEL_ALIASES in config.py")
    body = m.group(2)
    line_re = re.compile(rf'^\s*"{re.escape(key)}"\s*:\s*.*$', re.M)
    new_line = f'    "{key}": "{report_boat}",'
    if line_re.search(body):
        body = line_re.sub(new_line, body)
    else:
        body = body.rstrip() + f"\n{new_line}\n"
    return text[: m.start()] + m.group(1) + body + m.group(3) + text[m.end() :]


def append_feedback_rows(confirmations: list[dict], rejections: list[dict]) -> None:
    text = FEEDBACK_PATH.read_text()
    today = date.today().isoformat()
    if confirmations:
        marker = "## Confirmed MMSI mappings"
        idx = text.find(marker)
        if idx < 0:
            raise SystemExit("FEEDBACK.md missing Confirmed MMSI mappings section")
        # Insert after header table separator line following the section.
        table_head = "| Report boat name | MMSI | AIS name | Notes |"
        pos = text.find(table_head, idx)
        if pos < 0:
            raise SystemExit("FEEDBACK.md confirmed table header missing")
        # find end of table: next ## heading
        next_h = text.find("\n## ", pos)
        table = text[pos:next_h] if next_h > 0 else text[pos:]
        for row in confirmations:
            line = (
                f"| {row['report_boat']} | {row['mmsi']} | {row.get('ais_name') or ''} | "
                f"Human confirm {today}"
                f"{('; ' + row['notes']) if row.get('notes') else ''} |"
            )
            if str(row["mmsi"]) in table and row["report_boat"] in table:
                continue
            table = table.rstrip() + "\n" + line + "\n"
        if next_h > 0:
            text = text[:pos] + table + text[next_h:]
        else:
            text = text[:pos] + table

    if rejections:
        marker = "## Wrong automated matches (reject)"
        idx = text.find(marker)
        if idx < 0:
            raise SystemExit("FEEDBACK.md missing reject section")
        table_head = "| AIS name / MMSI | Incorrectly matched report boat | Action |"
        pos = text.find(table_head, idx)
        next_h = text.find("\n## ", pos)
        table = text[pos:next_h] if next_h > 0 else text[pos:]
        for row in rejections:
            label = f"{row.get('ais_name') or 'MMSI'} / {row['mmsi']}"
            line = (
                f"| {label} | {row.get('report_boat') or ''} | "
                f"Denied (human {today}"
                f"{('; ' + row['notes']) if row.get('notes') else ''}) |"
            )
            if str(row["mmsi"]) in table:
                continue
            table = table.rstrip() + "\n" + line + "\n"
        if next_h > 0:
            text = text[:pos] + table + text[next_h:]
        else:
            text = text[:pos] + table

    FEEDBACK_PATH.write_text(text)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("feedback", type=Path, help="JSON downloaded from verify-mmsi.html")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    data = load_feedback(args.feedback)
    confirmations = []
    for row in data.get("confirmations") or []:
        mmsi = int(row.get("mmsi") or 0)
        boat = (row.get("report_boat") or "").strip()
        if mmsi <= 0 or not boat:
            continue
        confirmations.append(
            {
                "report_boat": boat,
                "mmsi": mmsi,
                "ais_name": (row.get("ais_name") or "").strip(),
                "notes": (row.get("notes") or "").strip(),
            }
        )
    rejections = []
    for row in data.get("rejections") or []:
        mmsi = int(row.get("mmsi") or 0)
        if mmsi <= 0:
            continue
        rejections.append(
            {
                "report_boat": (row.get("report_boat") or "").strip(),
                "mmsi": mmsi,
                "ais_name": (row.get("ais_name") or "").strip(),
                "notes": (row.get("notes") or "").strip(),
            }
        )

    if not confirmations and not rejections:
        raise SystemExit("No confirmations or rejections found in feedback file")

    print(f"Confirmations: {len(confirmations)}")
    for c in confirmations:
        print(f"  + {c['report_boat']} -> {c['mmsi']} ({c.get('ais_name') or 'no AIS name'})")
    print(f"Rejections: {len(rejections)}")
    for r in rejections:
        print(f"  - {r['mmsi']} ({r.get('ais_name') or '?'}) for {r.get('report_boat')}")

    if args.dry_run:
        print("Dry run — no files written")
        return

    cfg = CONFIG_PATH.read_text()
    allow_vals = {c["mmsi"]: f"{c.get('ais_name') or c['report_boat']} / {c['report_boat']}" for c in confirmations}
    deny_vals = {
        r["mmsi"]: f"{r.get('ais_name') or 'MMSI'} rejected for {r.get('report_boat') or 'unknown'}"
        for r in rejections
    }
    map_vals = {c["mmsi"]: c["report_boat"] for c in confirmations}
    cfg = upsert_config_set(cfg, "MMSI_ALLOWLIST", allow_vals)
    if deny_vals:
        cfg = upsert_config_set(cfg, "MMSI_DENYLIST", deny_vals)
    cfg = upsert_config_dict(cfg, "MMSI_TO_REPORT_BOAT", map_vals)
    for c in confirmations:
        if c.get("ais_name"):
            cfg = upsert_alias(cfg, c["ais_name"], c["report_boat"])
    CONFIG_PATH.write_text(cfg)
    append_feedback_rows(confirmations, rejections)

    # Keep a copy under data/processed for the audit trail.
    out = ROOT / "data" / "processed" / "mmsi_human_feedback.json"
    out.write_text(json.dumps(data, indent=2))
    print(f"Updated {CONFIG_PATH.relative_to(ROOT)}")
    print(f"Updated {FEEDBACK_PATH.relative_to(ROOT)}")
    print(f"Wrote {out.relative_to(ROOT)}")
    print(
        "Next: re-extract AIS for affected days (or --force range), then "
        "refine_registry → detect_stops → build_map_data → export_unmatched_boats."
    )


if __name__ == "__main__":
    main()
