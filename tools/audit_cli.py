"""
Run the BrnzyBot raid audit from the shell — offline (fixtures) or live (creds).
The exact core path the /audit cog uses, minus Discord, so it's verifiable here.

  # offline whole-roster against the synthetic example log (no creds):
  python -m tools.audit_cli --fixtures SYNTH0000000001

  # offline single raider:
  python -m tools.audit_cli --fixtures SYNTH0000000001 Pyra

  # live (needs WCL_CLIENT_ID / WCL_CLIENT_SECRET):
  python -m tools.audit_cli "https://classic.warcraftlogs.com/reports/<code>#fight=last" [char] [spec]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.fixtures import FIXTURE_WCL_DIR, ensure_item_db, use_wcl_fixtures


def _spec_resolver(code: str):
    """resolve_spec(name, wow_class) backed by a <code>.specs.json fixture."""
    try:
        with open(os.path.join(FIXTURE_WCL_DIR, f"{code}.specs.json"), encoding="utf-8") as f:
            mapping = json.load(f)
    except FileNotFoundError:
        mapping = {}
    return lambda name, wow_class="": mapping.get(name.lower())


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the raid audit from the shell.")
    ap.add_argument("report", help="WCL report URL or 16-char code")
    ap.add_argument("character", nargs="?", help="single raider (omit = whole roster)")
    ap.add_argument("spec", nargs="?", help="spec key for a single live audit")
    ap.add_argument("--fixtures", action="store_true",
                    help="replay tests/fixtures/wcl instead of calling WCL (no creds)")
    args = ap.parse_args()

    if args.fixtures:
        use_wcl_fixtures()
    if ensure_item_db() is None:
        print("warning: item DB fixture missing — empty-socket detection disabled",
              file=sys.stderr)

    from core.audit.report import build_audit, build_roster_audit, parse_report_url

    code, _ = parse_report_url(args.report)
    code = code or args.report
    url = args.report if "reports/" in args.report else \
        f"https://classic.warcraftlogs.com/reports/{code}"

    if args.character:
        spec = args.spec or _spec_resolver(code)(args.character)
        if not spec:
            print(f"Need a spec for {args.character} (pass it as an arg, "
                  f"or add it to {code}.specs.json).")
            return
        print(build_audit(url, args.character, spec).render())
    else:
        print(build_roster_audit(url, _spec_resolver(code)).render())


if __name__ == "__main__":
    main()
