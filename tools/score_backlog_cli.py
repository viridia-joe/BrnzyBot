"""
tools/score_backlog_cli.py — review items the gear pipeline couldn't EP-score.

These are mostly on-use/proc trinkets (Quagmirran's Eye, Eye of Moam, …) that the
static EP model can't value. Run this periodically during development to see what's
accumulated, then hand-score them into the item DB / a proc-value table.

    python3 -m tools.score_backlog_cli            # list everything
    python3 -m tools.score_backlog_cli --spec ele_shaman
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import config
    PATH = os.path.join(os.path.dirname(config.BOT_DB_PATH), "score_backlog.jsonl")
except Exception:
    PATH = os.path.expanduser("~/.openclaw/data/score_backlog.jsonl")


def main() -> None:
    ap = argparse.ArgumentParser(description="Review unscored gear items.")
    ap.add_argument("--spec", help="Filter to one spec key.")
    args = ap.parse_args()

    if not os.path.exists(PATH):
        print(f"No backlog yet ({PATH}).")
        return

    rows = []
    with open(PATH, encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if args.spec:
        rows = [r for r in rows if r.get("spec") == args.spec]

    if not rows:
        print("Nothing to review.")
        return

    # Group by item so the same trinket across specs shows its spec list.
    by_item: dict[int, dict] = {}
    for r in rows:
        iid = r.get("item_id")
        e = by_item.setdefault(iid, {"name": r.get("name"), "slot": r.get("slot"),
                                     "specs": set(), "reason": r.get("reason", "")})
        e["specs"].add(r.get("spec"))

    print(f"{len(by_item)} unscored item(s):\n")
    for iid, e in sorted(by_item.items(), key=lambda kv: kv[1]["slot"]):
        specs = ", ".join(sorted(s for s in e["specs"] if s))
        print(f"  [{iid}] {e['name']}  ({e['slot']})")
        print(f"       seen for: {specs}")
        print(f"       {e['reason']}\n")


if __name__ == "__main__":
    main()
