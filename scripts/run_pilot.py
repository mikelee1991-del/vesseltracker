#!/usr/bin/env python3
"""Run the pilot pipeline end-to-end with configurable windows."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str]):
    print("+", " ".join(cmd), flush=True)
    subprocess.check_call(cmd, cwd=ROOT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report-start", default=None)
    ap.add_argument("--report-end", default=None)
    ap.add_argument("--ais-start", default=None)
    ap.add_argument("--ais-end", default=None)
    ap.add_argument("--skip-scrape", action="store_true")
    ap.add_argument("--skip-ais", action="store_true")
    ap.add_argument("--scrape-workers", type=int, default=4)
    ap.add_argument("--ais-workers", type=int, default=6)
    args = ap.parse_args()

    py = sys.executable
    if not args.skip_scrape:
        cmd = [py, "scripts/scrape_fish_reports.py", "--workers", str(args.scrape_workers)]
        if args.report_start:
            cmd += ["--start", args.report_start]
        if args.report_end:
            cmd += ["--end", args.report_end]
        run(cmd)

    if not args.skip_ais:
        cmd = [py, "scripts/extract_ais.py", "--workers", str(args.ais_workers)]
        if args.ais_start:
            cmd += ["--start", args.ais_start]
        if args.ais_end:
            cmd += ["--end", args.ais_end]
        run(cmd)
        run([py, "scripts/refine_registry.py"])
        run([py, "scripts/detect_stops.py"])

    run([py, "scripts/build_map_data.py"])
    print("Pilot pipeline complete.")


if __name__ == "__main__":
    main()
