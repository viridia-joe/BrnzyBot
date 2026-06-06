"""
Capture real WCL responses for a report into tests/fixtures/wcl/, so the audit and
rotationcheck can be replayed offline (set WCL_FIXTURE_DIR / use tools.fixtures).

Run from a machine that HAS creds (your desktop / the VM):

    WCL_CLIENT_ID=... WCL_CLIENT_SECRET=... \
        python -m tools.capture_wcl "https://classic.warcraftlogs.com/reports/<code>" [--all]

By default it captures the longest kill (the fight the audit auto-selects); --all
captures every fight in the report. Writes:
    <code>.fights, <code>.actors, <code>.abilities,
    <code>.combatant.<fid>, <code>.casts.<fid>,
    recent_reports.<player>            (so /rotationcheck auto-resolution replays too)

The data is public log content; player names are fine to commit. Do NOT run this
with WCL_FIXTURE_DIR set (that would replay instead of capture).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.fixtures import FIXTURE_WCL_DIR

_CODE_RE = re.compile(r"reports/([A-Za-z0-9]+)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Capture WCL fixtures for offline replay.")
    ap.add_argument("report", help="WCL report URL or code")
    ap.add_argument("--all", action="store_true", help="capture every fight (default: longest kill)")
    args = ap.parse_args()

    if os.environ.get("WCL_FIXTURE_DIR"):
        sys.exit("refusing to capture while WCL_FIXTURE_DIR is set (that replays).")

    m = _CODE_RE.search(args.report)
    code = m.group(1) if m else args.report

    from core import wcl_client as wcl

    os.makedirs(FIXTURE_WCL_DIR, exist_ok=True)

    def dump(name, obj):
        with open(os.path.join(FIXTURE_WCL_DIR, f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump(obj, f)

    fights = wcl.get_fights(code)
    actors = wcl.get_master_actors(code)
    dump(f"{code}.fights", fights)
    dump(f"{code}.actors", actors)
    dump(f"{code}.abilities", wcl.get_abilities(code))

    if args.all:
        target = fights
    else:
        kills = [f for f in fights if f.get("kill")] or fights
        target = [max(kills, key=lambda f: f.get("endTime", 0) - f.get("startTime", 0))] if kills else []

    for f in target:
        fid = f["id"]
        dump(f"{code}.combatant.{fid}", wcl.get_combatant_info(code, fid))
        dump(f"{code}.casts.{fid}", wcl.get_casts(code, fid))
        print(f"  captured fight {fid}: {f.get('name')}")

    for a in actors:
        name = a.get("name")
        if name:
            dump(f"recent_reports.{name.lower()}", [{"code": code, "startTime": 1}])

    print(f"captured {len(target)} fight(s) for {code} → {FIXTURE_WCL_DIR}")


if __name__ == "__main__":
    main()
