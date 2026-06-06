#!/usr/bin/env python3
"""
Parse WowSims all_gems.go into data/gem_db.json (gem id -> name, color, quality,
phase). Authoritative gem-color source for the audit's meta-gem activation check.
One-time import (re-run if WowSims updates).

    curl -s https://raw.githubusercontent.com/wowsims/tbc/master/sim/core/items/all_gems.go -o /tmp/all_gems.go
    python3 scripts/import-gems.py
"""

import json
import os
import re

INPUT = "/tmp/all_gems.go"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "gem_db.json")

_QMAP = {"Poor": "poor", "Common": "common", "Uncommon": "uncommon",
         "Rare": "rare", "Epic": "epic", "Legendary": "legendary"}

_RX = re.compile(
    r'\{Name:\s*"((?:[^"\\]|\\.)*)",\s*ID:\s*(\d+),\s*Phase:\s*(\d+),'
    r'\s*Quality:\s*proto\.ItemQuality_ItemQuality(\w+),'
    r'\s*Color:\s*proto\.GemColor_GemColor(\w+)'
)


def main():
    src = open(INPUT, encoding="utf-8").read()
    db = {}
    for name, iid, phase, qual, color in _RX.findall(src):
        db[int(iid)] = {"name": name, "color": color,
                        "quality": _QMAP.get(qual, qual.lower()), "phase": int(phase)}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({str(k): db[k] for k in sorted(db)}, f, separators=(",", ":"))
    metas = sum(1 for v in db.values() if v["color"] == "Meta")
    print(f"wrote {len(db)} gems ({metas} meta) → {OUT}")


if __name__ == "__main__":
    main()
