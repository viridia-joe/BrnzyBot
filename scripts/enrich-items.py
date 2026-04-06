#!/usr/bin/env python3
"""
Enrich the local item database with source info and drop rates from Wowhead.

One-time run (~10-15 minutes for all items). Re-run when new phase drops.
Skips items that already have source data.

Reads/writes: ~/.openclaw/data/tbc_items.db
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

# Source classification based on Wowhead tooltip content and known IDs
RAID_BOSSES_10 = {
    "Karazhan", "Zul'Aman",
}

RAID_BOSSES_25 = {
    "Gruul's Lair", "Magtheridon's Lair", "Serpentshrine Cavern",
    "Tempest Keep", "Hyjal Summit", "Black Temple", "Sunwell Plateau",
}

WORLD_BOSSES = {
    "Doom Lord Kazzak", "Doomwalker",
}

# Known badge vendor item IDs (G'eras in Shattrath)
# We'll detect these from the tooltip mentioning "Badge of Justice"


def classify_source(tooltip_html, item_name, item_id):
    """
    Classify item source from Wowhead tooltip HTML.
    Returns (source_type, source_name, drop_rate).
    """
    if not tooltip_html:
        return "Unknown", "", 0

    source_type = "Unknown"
    source_name = ""
    drop_rate = 0

    # Check for crafted items
    if "Created by" in tooltip_html or "Plans:" in tooltip_html or "Pattern:" in tooltip_html or "Recipe:" in tooltip_html:
        source_type = "Crafted"
        # Try to find profession
        prof_match = re.search(r"Requires\s+(Tailoring|Leatherworking|Blacksmithing|Engineering|Jewelcrafting|Enchanting|Alchemy)", tooltip_html)
        if prof_match:
            source_name = f"Crafted ({prof_match.group(1)})"
        else:
            source_name = "Crafted"
        return source_type, source_name, 100

    # Check for quest rewards
    if "Quest:" in tooltip_html or "Reward from" in tooltip_html:
        source_type = "Quest"
        return source_type, "Quest Reward", 100

    # Check for reputation vendor
    if "Requires" in tooltip_html and ("Revered" in tooltip_html or "Exalted" in tooltip_html or "Honored" in tooltip_html or "Friendly" in tooltip_html):
        source_type = "Reputation"
        rep_match = re.search(r"Requires\s+([^<\n]+?)\s*-\s*(Friendly|Honored|Revered|Exalted)", tooltip_html)
        if rep_match:
            source_name = f"{rep_match.group(1).strip()} - {rep_match.group(2)}"
        else:
            source_name = "Reputation Vendor"
        return source_type, source_name, 100

    # Check for PvP / Arena
    if "Arena" in tooltip_html or "Gladiator" in item_name or "General's" in item_name or "Marshal's" in item_name:
        source_type = "Arena"
        source_name = "Arena / PvP Vendor"
        return source_type, source_name, 100

    if "Honor" in tooltip_html or "Mark of" in tooltip_html:
        source_type = "PvP"
        source_name = "Honor Vendor"
        return source_type, source_name, 100

    # Check for Badge of Justice
    if "Badge of Justice" in tooltip_html:
        source_type = "Badge"
        badge_match = re.search(r"(\d+)\s*Badge", tooltip_html)
        count = badge_match.group(1) if badge_match else "?"
        source_name = f"{count} Badges of Justice"
        return source_type, source_name, 100

    return source_type, source_name, drop_rate


def fetch_wowhead_source(item_id):
    """
    Fetch item source data from Wowhead's tooltip API and item page.
    Returns (source_type, source_name, drop_rate).
    """
    # First get the tooltip for basic classification
    try:
        req = Request(f"https://nether.wowhead.com/tbc/tooltip/item/{item_id}")
        req.add_header("User-Agent", "Mozilla/5.0")
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            tooltip = data.get("tooltip", "")
            name = data.get("name", "")
    except Exception:
        return "Unknown", "", 0

    # Try to classify from tooltip
    source_type, source_name, drop_rate = classify_source(tooltip, name, item_id)
    if source_type != "Unknown":
        return source_type, source_name, drop_rate

    # For unclassified items, try to get drop info from the item page
    # Wowhead's item pages have source info but are JS-heavy.
    # The tooltip usually has "Dropped by" for boss drops though.
    if "Dropped by" in tooltip:
        # Extract boss name from tooltip
        boss_match = re.search(r'Dropped by[^<]*<a[^>]*>([^<]+)</a>', tooltip)
        if boss_match:
            boss_name = boss_match.group(1)
            source_name = boss_name

            # Classify by known raid/dungeon
            for wb in WORLD_BOSSES:
                if wb.lower() in boss_name.lower():
                    return "World Boss", boss_name, 0

            # Check if it's a raid boss (we'll refine this with zone data later)
            source_type = "Boss Drop"
            return source_type, boss_name, 0

    # Check for zone drop / BoE
    if "Zone:" in tooltip or "World Drop" in tooltip:
        return "World Drop", "BoE World Drop", 0

    return "Unknown", "", 0


def enrich_from_known_sources(db_conn):
    """
    Use known TBC source data to fill in common items without hitting Wowhead.
    This covers the most important items that players care about.
    """
    c = db_conn.cursor()

    # Known source mappings for important items (item_id → source)
    # Format: item_id: (source_type, source_name, drop_rate)
    known_sources = {
        # Karazhan drops
        28770: ("10-man Raid", "Karazhan - Prince Malchezaar", 14),
        28762: ("10-man Raid", "Karazhan - Prince Malchezaar", 12),
        28963: ("10-man Raid", "Karazhan - Prince Malchezaar", 12),
        28766: ("10-man Raid", "Karazhan - Prince Malchezaar", 12),
        28764: ("10-man Raid", "Karazhan - Prince Malchezaar", 12),
        28765: ("10-man Raid", "Karazhan - Prince Malchezaar", 12),
        28585: ("10-man Raid", "Karazhan - Netherspite", 15),
        28744: ("10-man Raid", "Karazhan - Shade of Aran", 15),
        28672: ("10-man Raid", "Karazhan - Opera Event", 15),
        28587: ("10-man Raid", "Karazhan - Opera Event (Wizard of Oz)", 15),
        28507: ("10-man Raid", "Karazhan - Terestian Illhoof", 15),
        28779: ("10-man Raid", "Karazhan - Terestian Illhoof", 15),
        28780: ("10-man Raid", "Karazhan - Magtheridon's Lair - Magtheridon", 15),  # Actually Mag
        28785: ("10-man Raid", "Karazhan - Terestian Illhoof", 15),
        28530: ("10-man Raid", "Karazhan - Moroes", 15),
        28528: ("10-man Raid", "Karazhan - Moroes", 15),
        28545: ("10-man Raid", "Karazhan - Attumen the Huntsman", 15),
        28509: ("10-man Raid", "Karazhan - The Curator", 15),
        28633: ("10-man Raid", "Karazhan - The Curator", 15),
        28570: ("10-man Raid", "Karazhan - Maiden of Virtue", 15),

        # Gruul's Lair
        28795: ("25-man Raid", "Gruul's Lair - High King Maulgar", 15),
        28797: ("25-man Raid", "Gruul's Lair - High King Maulgar", 15),
        28822: ("25-man Raid", "Gruul's Lair - Gruul the Dragonkiller", 15),
        28794: ("25-man Raid", "Gruul's Lair - Gruul the Dragonkiller", 15),
        28810: ("25-man Raid", "Gruul's Lair - Gruul the Dragonkiller", 15),

        # Magtheridon
        28789: ("25-man Raid", "Magtheridon's Lair - Magtheridon", 15),
        28780: ("25-man Raid", "Magtheridon's Lair - Magtheridon", 15),
        29458: ("25-man Raid", "Magtheridon's Lair - Magtheridon", 15),

        # World bosses
        30725: ("World Boss", "Doomwalker", 15),
        30735: ("World Boss", "Doom Lord Kazzak", 15),
        30726: ("World Boss", "Doomwalker", 15),
        30727: ("World Boss", "Doomwalker", 15),
        30728: ("World Boss", "Doomwalker", 15),
        30729: ("World Boss", "Doomwalker", 15),
        30730: ("World Boss", "Doom Lord Kazzak", 15),
        30731: ("World Boss", "Doom Lord Kazzak", 15),
        30732: ("World Boss", "Doom Lord Kazzak", 15),
        30733: ("World Boss", "Doom Lord Kazzak", 15),
        30734: ("World Boss", "Doom Lord Kazzak", 15),

        # Badge vendor (G'eras)
        29370: ("Badge", "41 Badges of Justice", 100),
        29376: ("Badge", "41 Badges of Justice", 100),
        29383: ("Badge", "25 Badges of Justice", 100),
        33296: ("Badge", "50 Badges of Justice", 100),

        # Crafted
        24266: ("Crafted", "Tailoring (Spellstrike Hood)", 100),
        24262: ("Crafted", "Tailoring (Spellstrike Pants)", 100),
        21871: ("Crafted", "Tailoring (Frozen Shadoweave Robe)", 100),
        21870: ("Crafted", "Tailoring (Frozen Shadoweave Boots)", 100),
        21869: ("Crafted", "Tailoring (Frozen Shadoweave Shoulders)", 100),
        24256: ("Crafted", "Tailoring (Girdle of Ruination)", 100),
        24253: ("Crafted", "Tailoring (Bracers of Havok)", 100),
    }

    updated = 0
    for item_id, (stype, sname, drate) in known_sources.items():
        effort = EFFORT_MAP.get(stype, 5.0)
        c.execute(
            "UPDATE items SET source_type=?, source_name=?, drop_rate=?, effort_score=? WHERE item_id=?",
            (stype, sname, drate, effort, item_id),
        )
        if c.rowcount > 0:
            updated += 1

    db_conn.commit()
    return updated


EFFORT_MAP = {
    "Quest": 1.0,
    "Reputation": 2.0,
    "Badge": 2.5,
    "Crafted": 3.0,
    "Heroic Dungeon": 3.0,
    "Normal Dungeon": 2.0,
    "Boss Drop": 4.0,
    "10-man Raid": 5.0,
    "25-man Raid": 6.0,
    "World Boss": 9.0,
    "Arena": 6.0,
    "PvP": 4.0,
    "World Drop": 7.0,
    "Unknown": 5.0,
}


def main():
    print("Enriching item database with source data...")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # First pass: apply known sources
    print("  Applying known source mappings...")
    known_count = enrich_from_known_sources(conn)
    print(f"  Updated {known_count} items from known sources")

    # Second pass: fetch from Wowhead for items without sources
    # Only process Epic and Rare items (the ones players care about)
    c.execute(
        "SELECT item_id, name FROM items WHERE source_type = '' AND quality IN ('Epic', 'Rare') ORDER BY phase, ilvl DESC"
    )
    items_to_enrich = c.fetchall()
    print(f"  {len(items_to_enrich)} items need Wowhead enrichment")

    enriched = 0
    errors = 0
    for i, (item_id, name) in enumerate(items_to_enrich):
        if i % 100 == 0 and i > 0:
            print(f"  Progress: {i}/{len(items_to_enrich)} ({enriched} enriched, {errors} errors)")
            conn.commit()

        try:
            source_type, source_name, drop_rate = fetch_wowhead_source(item_id)
            effort = EFFORT_MAP.get(source_type, 5.0)

            c.execute(
                "UPDATE items SET source_type=?, source_name=?, drop_rate=?, effort_score=? WHERE item_id=?",
                (source_type, source_name, drop_rate, effort, item_id),
            )
            enriched += 1

        except Exception as e:
            errors += 1

        # Rate limit: be polite to Wowhead
        time.sleep(0.3)

    conn.commit()

    # Report
    c.execute("SELECT source_type, COUNT(*) FROM items WHERE source_type != '' GROUP BY source_type ORDER BY COUNT(*) DESC")
    print(f"\n  Enrichment complete: {enriched} items updated, {errors} errors")
    print("  Source distribution:")
    for row in c.fetchall():
        print(f"    {row[0]}: {row[1]}")

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
