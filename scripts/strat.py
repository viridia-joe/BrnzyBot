#!/usr/bin/env python3
"""
Discord command: /strat <boss>
Concise raid strategy summary for TBC boss fights.

Usage:
  python3 strat.py Prince
  python3 strat.py Gruul
  python3 strat.py all          # list all bosses
  python3 strat.py Kara          # list all Kara bosses
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from bot_footer import FOOTER

DATA_FILE = os.path.expanduser("~/.openclaw/data/boss_strats.json")


def load_strats():
    with open(DATA_FILE) as f:
        return json.load(f)


def find_boss(strats, query):
    """Find a boss by partial name match."""
    query_lower = query.lower().strip()

    # Check for raid-wide listing
    raid_aliases = {
        "kara": "Karazhan",
        "karazhan": "Karazhan",
        "gruul": "Gruul's Lair",
        "gruuls": "Gruul's Lair",
        "mag": "Magtheridon's Lair",
        "mags": "Magtheridon's Lair",
        "magtheridon": "Magtheridon's Lair",
        "ssc": "Serpentshrine Cavern",
        "serpentshrine": "Serpentshrine Cavern",
        "tk": "Tempest Keep",
        "tempest": "Tempest Keep",
        "eye": "Tempest Keep",
    }

    # Check if it's a raid name → list all bosses
    if query_lower in raid_aliases:
        raid = raid_aliases[query_lower]
        bosses = [b for b in strats if b["raid"] == raid]
        return None, bosses, raid

    # Search by boss name
    seen_ids = set()
    matches = []
    for boss in strats:
        if id(boss) in seen_ids:
            continue
        boss_name = boss["name"].lower()
        # Exact match
        if query_lower == boss_name:
            return boss, [], None
        # Partial match on name
        matched = False
        if query_lower in boss_name or boss_name in query_lower:
            matched = True
        # Check aliases
        if not matched:
            for alias in boss.get("aliases", []):
                if query_lower == alias.lower() or query_lower in alias.lower():
                    matched = True
                    break
        if matched:
            matches.append(boss)
            seen_ids.add(id(boss))

    if len(matches) == 1:
        return matches[0], [], None
    elif len(matches) > 1:
        return None, matches, None
    return None, [], None


def format_boss(boss):
    """Format a single boss strategy for Discord."""
    lines = []
    lines.append(f"**{boss['name']}** — {boss['raid']}")
    lines.append(f"*{boss['type']}*")
    lines.append("")
    lines.append(boss["summary"])
    lines.append("")

    lines.append("**Key Abilities:**")
    for ability in boss["abilities"]:
        lines.append(f"- **{ability['name']}** — {ability['desc']}")
    lines.append("")

    lines.append("**What Kills People:**")
    for killer in boss["killers"]:
        lines.append(f"- {killer}")
    lines.append("")

    if boss.get("prep"):
        lines.append("**Prep:**")
        for prep in boss["prep"]:
            lines.append(f"- {prep}")
        lines.append("")

    if boss.get("tips"):
        lines.append("**Tips:**")
        for tip in boss["tips"]:
            lines.append(f"- {tip}")

    return "\n".join(lines)


def format_boss_list(bosses, raid_name=None):
    """Format a list of bosses for Discord."""
    lines = []
    if raid_name:
        lines.append(f"**{raid_name}** — Boss List")
    else:
        lines.append("**Multiple matches:**")
    lines.append("")
    for boss in bosses:
        lines.append(f"- **{boss['name']}** — {boss['type']}")
    lines.append("")
    lines.append("Use `/strat <boss name>` for details.")
    return "\n".join(lines)


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: `/strat <boss or raid>`\nExamples: `/strat Prince`, `/strat Kara`, `/strat Gruul`")
        return

    query = " ".join(args)

    if query.lower() == "all":
        strats = load_strats()
        current_raid = None
        lines = ["**All TBC Bosses**", ""]
        for boss in strats:
            if boss["raid"] != current_raid:
                current_raid = boss["raid"]
                lines.append(f"\n**{current_raid}** (Phase {boss['phase']})")
            lines.append(f"  - {boss['name']}")
        print("\n".join(lines))
        return

    strats = load_strats()
    boss, matches, raid_name = find_boss(strats, query)

    if boss:
        print(format_boss(boss) + FOOTER)
    elif matches:
        print(format_boss_list(matches, raid_name) + FOOTER)
    else:
        print(f"No boss found matching \"{query}\". Try `!strat all` to see all bosses.")


if __name__ == "__main__":
    main()
