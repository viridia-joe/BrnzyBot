#!/usr/bin/env python3
"""
Fetch item data from Wowhead for any items in the database with source_type='pending'.
These are items encountered during gearcheck that weren't in the original WowSims import.

Runs locally, no LLM needed. Safe to run on a schedule or heartbeat.
"""

import json
import os
import re
import sqlite3
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

DB_PATH = os.path.expanduser("~/.openclaw/data/tbc_items.db")

# Map Wowhead inventory types to our slot names
INVENTORY_TYPE_MAP = {
    1: "Head", 2: "Neck", 3: "Shoulder", 4: "Shirt", 5: "Chest",
    6: "Waist", 7: "Legs", 8: "Feet", 9: "Wrist", 10: "Hands",
    11: "Ring", 12: "Trinket", 13: "One Hand", 14: "Off Hand",
    15: "Ranged", 16: "Back", 17: "Two-Hand", 18: "Bag",
    20: "Chest", 21: "Main Hand", 22: "Off Hand", 23: "Off Hand",
    24: "Ammo", 25: "Thrown", 26: "Ranged", 28: "Relic",
}

# Stat name mapping from Wowhead tooltip HTML to our stat names
STAT_PATTERNS = [
    (r"(\d+) Stamina", "Stamina"),
    (r"(\d+) Intellect", "Intellect"),
    (r"(\d+) Spirit", "Spirit"),
    (r"(\d+) Agility", "Agility"),
    (r"(\d+) Strength", "Strength"),
    (r"Equip: Increases damage and healing done by magical spells and effects by up to (\d+)", "SpellPower"),
    (r"Equip: Increases healing done by up to (\d+)", "HealingPower"),
    (r"Equip: Increases your spell critical strike rating by (\d+)", "SpellCrit"),
    (r"Equip: Increases your spell hit rating by (\d+)", "SpellHit"),
    (r"Equip: Increases your spell haste rating by (\d+)", "SpellHaste"),
    (r"Equip: Increases attack power by (\d+)", "AttackPower"),
    (r"Equip: Increases your critical strike rating by (\d+)", "MeleeCrit"),
    (r"Equip: Increases your hit rating by (\d+)", "MeleeHit"),
    (r"Equip: Increases your haste rating by (\d+)", "MeleeHaste"),
    (r"Equip: Increases your expertise rating by (\d+)", "Expertise"),
    (r"Equip: Increases defense rating by (\d+)", "Defense"),
    (r"Equip: Increases your dodge rating by (\d+)", "Dodge"),
    (r"Equip: Increases your parry rating by (\d+)", "Parry"),
    (r"Equip: Increases your shield block rating by (\d+)", "Block"),
    (r"Equip: Increases the block value of your shield by (\d+)", "BlockValue"),
    (r"Equip: Increases your resilience rating by (\d+)", "Resilience"),
    (r"Equip: Restores (\d+) mana per 5 sec", "MP5"),
    (r"Equip: Increases damage done by Shadow spells and effects by up to (\d+)", "ShadowSpellPower"),
    (r"Equip: Increases damage done by Fire spells and effects by up to (\d+)", "FireSpellPower"),
    (r"Equip: Increases damage done by Frost spells and effects by up to (\d+)", "FrostSpellPower"),
    (r"Equip: Increases damage done by Nature spells and effects by up to (\d+)", "NatureSpellPower"),
    (r"Equip: Increases damage done by Arcane spells and effects by up to (\d+)", "ArcaneSpellPower"),
    (r"Equip: Increases your armor penetration rating by (\d+)", "ArmorPenetration"),
    (r"(\d+) Armor", "Armor"),
]

QUALITY_MAP = {
    0: "Unknown", 1: "Common", 2: "Uncommon", 3: "Rare", 4: "Epic", 5: "Legendary",
}


def fetch_item(item_id):
    """Fetch item data from Wowhead tooltip API."""
    try:
        req = Request(f"https://nether.wowhead.com/tbc/tooltip/item/{item_id}")
        req.add_header("User-Agent", "Mozilla/5.0")
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError) as e:
        return None


def parse_stats_from_tooltip(tooltip_html):
    """Extract stats from Wowhead tooltip HTML."""
    stats = {}
    for pattern, stat_name in STAT_PATTERNS:
        match = re.search(pattern, tooltip_html)
        if match:
            stats[stat_name] = float(match.group(1))
    return stats


def parse_quality(data):
    """Get quality from Wowhead data."""
    return QUALITY_MAP.get(data.get("quality", 0), "Unknown")


def parse_slot_from_tooltip(tooltip_html):
    """Try to determine slot from tooltip HTML."""
    slot_patterns = [
        (r"Head", "Head"), (r"Neck", "Neck"), (r"Shoulder", "Shoulder"),
        (r"Back", "Back"), (r"Chest", "Chest"), (r"Wrist", "Wrist"),
        (r"Hands", "Hands"), (r"Waist", "Waist"), (r"Legs", "Legs"),
        (r"Feet", "Feet"), (r"Finger", "Ring"), (r"Trinket", "Trinket"),
        (r"Main Hand", "Main Hand"), (r"Off Hand", "Off Hand"),
        (r"One-Hand", "One Hand"), (r"Two-Hand", "Two-Hand"),
        (r"Ranged", "Ranged"), (r"Relic", "Relic"), (r"Wand", "Wand"),
    ]
    for pattern, slot in slot_patterns:
        if re.search(pattern, tooltip_html):
            return slot
    return "Unknown"


def main():
    if not os.path.exists(DB_PATH):
        print("ERROR: Database not found.")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Find all pending items
    c.execute("SELECT item_id FROM items WHERE source_type = 'pending'")
    pending = [row[0] for row in c.fetchall()]

    if not pending:
        print("No pending items to enrich.")
        return

    print(f"Enriching {len(pending)} pending items from Wowhead...")

    enriched = 0
    failed = 0

    for item_id in pending:
        data = fetch_item(item_id)
        if not data:
            print(f"  {item_id}: fetch failed")
            failed += 1
            time.sleep(0.3)
            continue

        name = data.get("name", f"Unknown #{item_id}")
        tooltip = data.get("tooltip", "")
        quality = parse_quality(data)
        stats = parse_stats_from_tooltip(tooltip)
        slot = parse_slot_from_tooltip(tooltip)

        # Extract item level from tooltip
        ilvl_match = re.search(r"Item Level\s*(?:<!--ilvl-->)?(\d+)", tooltip)
        ilvl = int(ilvl_match.group(1)) if ilvl_match else 0

        c.execute("""
            UPDATE items SET
                name = ?, slot = ?, quality = ?, ilvl = ?,
                stats = ?, source_type = 'enriched'
            WHERE item_id = ?
        """, (name, slot, quality, ilvl, json.dumps(stats), item_id))

        print(f"  {item_id}: {name} ({quality}, iLvl {ilvl}, {len(stats)} stats)")
        enriched += 1
        time.sleep(0.3)

    conn.commit()
    conn.close()
    print(f"Done. Enriched: {enriched}, Failed: {failed}")


if __name__ == "__main__":
    main()
