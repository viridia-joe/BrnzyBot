#!/usr/bin/env python3
"""
Parse WowSims all_items.go into a local SQLite database.
One-time import (re-run if WowSims updates).

Input: /tmp/all_items.go (downloaded from GitHub)
Output: ~/.openclaw/data/tbc_items.db
"""

import json
import os
import re
import sqlite3

INPUT = "/tmp/all_items.go"
DB_PATH = os.path.expanduser("~/.openclaw/data/tbc_items.db")

# Map Go type names to readable slot names
SLOT_MAP = {
    "ItemTypeHead": "Head",
    "ItemTypeNeck": "Neck",
    "ItemTypeShoulder": "Shoulder",
    "ItemTypeBack": "Back",
    "ItemTypeChest": "Chest",
    "ItemTypeWrist": "Wrist",
    "ItemTypeHands": "Hands",
    "ItemTypeWaist": "Waist",
    "ItemTypeLegs": "Legs",
    "ItemTypeFeet": "Feet",
    "ItemTypeFinger": "Ring",
    "ItemTypeTrinket": "Trinket",
    "ItemTypeWeapon": "Weapon",
    "ItemTypeRanged": "Ranged",
}

QUALITY_MAP = {
    "ItemQualityCommon": "Common",
    "ItemQualityUncommon": "Uncommon",
    "ItemQualityRare": "Rare",
    "ItemQualityEpic": "Epic",
    "ItemQualityLegendary": "Legendary",
}

HAND_MAP = {
    "HandTypeMainHand": "Main Hand",
    "HandTypeOffHand": "Off Hand",
    "HandTypeTwoHand": "Two-Hand",
    "HandTypeOneHand": "One Hand",
}

WEAPON_TYPE_MAP = {
    "WeaponTypeSword": "Sword",
    "WeaponTypeMace": "Mace",
    "WeaponTypeAxe": "Axe",
    "WeaponTypeDagger": "Dagger",
    "WeaponTypeStaff": "Staff",
    "WeaponTypeFist": "Fist",
    "WeaponTypePolearm": "Polearm",
    "WeaponTypeShield": "Shield",
    "WeaponTypeOffHand": "Off Hand",
}

ARMOR_MAP = {
    "ArmorTypeCloth": "Cloth",
    "ArmorTypeLeather": "Leather",
    "ArmorTypeMail": "Mail",
    "ArmorTypePlate": "Plate",
}


def parse_item_line(line):
    """Parse a single Go struct literal into an item dict."""
    item = {}

    # Name
    m = re.search(r'Name:\s*"([^"]+)"', line)
    if m:
        item["name"] = m.group(1)
    else:
        return None

    # ID
    m = re.search(r'ID:\s*(\d+)', line)
    if m:
        item["item_id"] = int(m.group(1))

    # Phase
    m = re.search(r'Phase:\s*(\d+)', line)
    item["phase"] = int(m.group(1)) if m else 0

    # Item level
    m = re.search(r'Ilvl:\s*(\d+)', line)
    item["ilvl"] = int(m.group(1)) if m else 0

    # Quality
    m = re.search(r'Quality:\s*proto\.ItemQuality_(\w+)', line)
    item["quality"] = QUALITY_MAP.get(m.group(1), "Unknown") if m else "Unknown"

    # Slot type
    m = re.search(r'Type:\s*proto\.(ItemType_\w+)', line)
    raw_slot = m.group(1) if m else ""
    item["slot"] = SLOT_MAP.get(raw_slot.replace("ItemType_", ""), "Unknown")

    # For weapons, refine slot based on hand type
    if item["slot"] == "Weapon":
        m = re.search(r'HandType:\s*proto\.HandType_(\w+)', line)
        if m:
            hand = HAND_MAP.get(m.group(1), "")
            item["slot"] = hand if hand else "Weapon"

        # Check if it's a shield or off-hand
        m = re.search(r'WeaponType:\s*proto\.WeaponType_(\w+)', line)
        if m:
            wtype = m.group(1)
            item["weapon_type"] = WEAPON_TYPE_MAP.get(wtype, wtype)
            if wtype == "WeaponTypeShield":
                item["slot"] = "Off Hand"
            elif wtype == "WeaponTypeOffHand":
                item["slot"] = "Off Hand"

    # Wand detection
    m = re.search(r'RangedWeaponType:\s*proto\.RangedWeaponType_(\w+)', line)
    if m:
        rwt = m.group(1)
        if "Wand" in rwt:
            item["slot"] = "Wand"
        elif "Gun" in rwt or "Bow" in rwt or "Crossbow" in rwt or "Thrown" in rwt:
            item["slot"] = "Ranged"

    # Armor type
    m = re.search(r'ArmorType:\s*proto\.ArmorType_(\w+)', line)
    item["armor_type"] = ARMOR_MAP.get(m.group(1), "") if m else ""

    # Set name
    m = re.search(r'SetName:\s*"([^"]*)"', line)
    item["set_name"] = m.group(1) if m else ""

    # Unique
    item["is_unique"] = "Unique: true" in line

    # Stats — parse the stats.Stats{...} block
    stats = {}
    stats_match = re.search(r'Stats:\s*stats\.Stats\{([^}]*)\}', line)
    if stats_match:
        stats_str = stats_match.group(1)
        for sm in re.finditer(r'stats\.(\w+):\s*([\d.]+)', stats_str):
            stat_name = sm.group(1)
            stat_val = float(sm.group(2))
            if stat_val != 0:
                stats[stat_name] = stat_val
    item["stats"] = stats

    # Gem sockets
    sockets = []
    sock_match = re.search(r'GemSockets:\s*\[\]proto\.GemColor\{([^}]*)\}', line)
    if sock_match:
        for sm in re.finditer(r'GemColor_GemColor(\w+)', sock_match.group(1)):
            sockets.append(sm.group(1))
    item["sockets"] = sockets

    # Socket bonus
    bonus = {}
    bonus_match = re.search(r'SocketBonus:\s*stats\.Stats\{([^}]*)\}', line)
    if bonus_match:
        for sm in re.finditer(r'stats\.(\w+):\s*([\d.]+)', bonus_match.group(1)):
            bonus[sm.group(1)] = float(sm.group(2))
    item["socket_bonus"] = bonus

    # Class restrictions
    classes = []
    class_match = re.search(r'ClassAllowlist:\s*\[\]proto\.Class\{([^}]*)\}', line)
    if class_match:
        for cm in re.finditer(r'Class_Class(\w+)', class_match.group(1)):
            classes.append(cm.group(1))
    item["class_restriction"] = classes

    return item


def create_db(items):
    """Create SQLite database from parsed items."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE items (
            item_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            slot TEXT NOT NULL,
            phase INTEGER NOT NULL DEFAULT 0,
            quality TEXT NOT NULL DEFAULT 'Unknown',
            ilvl INTEGER NOT NULL DEFAULT 0,
            armor_type TEXT DEFAULT '',
            weapon_type TEXT DEFAULT '',
            set_name TEXT DEFAULT '',
            is_unique INTEGER DEFAULT 0,
            class_restriction TEXT DEFAULT '',
            stats TEXT NOT NULL DEFAULT '{}',
            sockets TEXT DEFAULT '[]',
            socket_bonus TEXT DEFAULT '{}',
            -- Enrichment fields (populated later by wowhead scraper)
            source_type TEXT DEFAULT '',
            source_name TEXT DEFAULT '',
            drop_rate REAL DEFAULT 0,
            effort_score REAL DEFAULT 0
        )
    """)

    c.execute("CREATE INDEX idx_slot ON items(slot)")
    c.execute("CREATE INDEX idx_phase ON items(phase)")
    c.execute("CREATE INDEX idx_quality ON items(quality)")
    c.execute("CREATE INDEX idx_name ON items(name)")

    for item in items:
        c.execute("""
            INSERT OR REPLACE INTO items
            (item_id, name, slot, phase, quality, ilvl, armor_type, weapon_type,
             set_name, is_unique, class_restriction, stats, sockets, socket_bonus)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            item["item_id"],
            item["name"],
            item["slot"],
            item["phase"],
            item["quality"],
            item["ilvl"],
            item.get("armor_type", ""),
            item.get("weapon_type", ""),
            item.get("set_name", ""),
            1 if item.get("is_unique") else 0,
            json.dumps(item.get("class_restriction", [])),
            json.dumps(item["stats"]),
            json.dumps(item.get("sockets", [])),
            json.dumps(item.get("socket_bonus", {})),
        ))

    conn.commit()
    conn.close()


def main():
    print("Parsing WowSims item data...")

    with open(INPUT) as f:
        content = f.read()

    # Each item is a single line starting with a tab and {
    items = []
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("{Name:"):
            item = parse_item_line(line)
            if item and item.get("item_id"):
                items.append(item)

    print(f"  Parsed {len(items)} items")

    # Stats summary
    slots = {}
    for item in items:
        slot = item["slot"]
        slots[slot] = slots.get(slot, 0) + 1
    for slot, count in sorted(slots.items(), key=lambda x: -x[1]):
        print(f"    {slot}: {count}")

    print(f"\n  Phase distribution:")
    phases = {}
    for item in items:
        p = item["phase"]
        phases[p] = phases.get(p, 0) + 1
    for p in sorted(phases):
        print(f"    Phase {p}: {phases[p]}")

    print(f"\nWriting to {DB_PATH}...")
    create_db(items)
    print(f"Done. {len(items)} items in database.")


if __name__ == "__main__":
    main()
