#!/usr/bin/env python3
"""
Map tier set pieces to their token drop sources.

TBC tier tokens drop from specific bosses. Players turn in the token
(+ class requirement) to get their class-specific set piece.
This script tags each set piece with where its token drops.
"""

import os
import sqlite3

DB_PATH = os.path.expanduser("~/.openclaw/data/tbc_items.db")

# T4 Token → Boss mapping
# Helm tokens: Prince Malchezaar (Karazhan)
# Shoulder tokens: High King Maulgar (Gruul's Lair)
# Chest tokens: Magtheridon (Magtheridon's Lair)
# Glove tokens: The Curator (Karazhan)
# Leg tokens: Gruul the Dragonkiller (Gruul's Lair)

# T5 Token → Boss mapping
# Helm tokens: Lady Vashj (SSC)
# Shoulder tokens: Void Reaver (TK)
# Chest tokens: Kael'thas Sunstrider (TK)
# Glove tokens: Leotheras the Blind (SSC)
# Leg tokens: Fathom-Lord Karathress (SSC)

# T6 Token → Boss mapping
# Helm tokens: Archimonde (Hyjal Summit)
# Shoulder tokens: Mother Shahraz (Black Temple)
# Chest tokens: Illidan Stormrage (Black Temple)
# Glove tokens: Azgalor (Hyjal Summit)
# Leg tokens: The Illidari Council (Black Temple)
# Bracers: Kalecgos (Sunwell) - T6.5
# Belt: Brutallus (Sunwell) - T6.5
# Boots: Felmyst (Sunwell) - T6.5

# All T4 set names
T4_SETS = [
    "Voidheart Raiment",                                    # Warlock
    "Aldor Regalia",                                        # Mage
    "Malorne Raiment", "Malorne Regalia", "Malorne Harness", # Druid
    "Cyclone Raiment", "Cyclone Regalia", "Cyclone Harness", # Shaman
    "Justicar Armor", "Justicar Raiment", "Justicar Battlegear",  # Paladin
    "Netherblade",                                          # Rogue
    "Demon Stalker Armor",                                  # Hunter
    "Warbringer Armor", "Warbringer Battlegear",            # Warrior
    "Incarnate Raiment", "Incarnate Regalia",               # Priest
]

T5_SETS = [
    "Corruptor Raiment",                                    # Warlock
    "Tirisfal Regalia",                                     # Mage
    "Nordrassil Raiment", "Nordrassil Regalia", "Nordrassil Harness",  # Druid
    "Cataclysm Raiment", "Cataclysm Regalia", "Cataclysm Harness",    # Shaman
    "Crystalforge Armor", "Crystalforge Raiment", "Crystalforge Battlegear",  # Paladin
    "Deathmantle",                                          # Rogue
    "Rift Stalker Armor",                                   # Hunter
    "Destroyer Armor", "Destroyer Battlegear",              # Warrior
    "Avatar Raiment", "Avatar Regalia",                     # Priest
]

T6_SETS = [
    "Malefic Raiment",                                      # Warlock
    "Tempest Regalia",                                      # Mage
    "Thunderheart Raiment", "Thunderheart Regalia", "Thunderheart Harness",  # Druid
    "Skyshatter Raiment", "Skyshatter Regalia", "Skyshatter Harness",        # Shaman
    "Lightbringer Armor", "Lightbringer Raiment", "Lightbringer Battlegear", # Paladin
    "Slayer's Armor",                                       # Rogue
    "Gronnstalker's Armor",                                 # Hunter
    "Onslaught Armor", "Onslaught Battlegear",              # Warrior
    "Absolution Raiment", "Absolution Regalia",             # Priest
]

# Slot → (source_type, source_name, drop_rate) for each tier
TIER_SLOT_BOSSES = {
    "T4": {
        "Head":     ("10-man Raid", "Karazhan - Prince Malchezaar (T4 Helm Token)", 33),
        "Shoulder": ("25-man Raid", "Gruul's Lair - High King Maulgar (T4 Shoulder Token)", 33),
        "Chest":    ("25-man Raid", "Magtheridon's Lair - Magtheridon (T4 Chest Token)", 33),
        "Hands":    ("10-man Raid", "Karazhan - The Curator (T4 Glove Token)", 33),
        "Legs":     ("25-man Raid", "Gruul's Lair - Gruul the Dragonkiller (T4 Leg Token)", 33),
    },
    "T5": {
        "Head":     ("25-man Raid", "SSC - Lady Vashj (T5 Helm Token)", 33),
        "Shoulder": ("25-man Raid", "TK - Void Reaver (T5 Shoulder Token)", 33),
        "Chest":    ("25-man Raid", "TK - Kael'thas Sunstrider (T5 Chest Token)", 33),
        "Hands":    ("25-man Raid", "SSC - Leotheras the Blind (T5 Glove Token)", 33),
        "Legs":     ("25-man Raid", "SSC - Fathom-Lord Karathress (T5 Leg Token)", 33),
    },
    "T6": {
        "Head":     ("25-man Raid", "Hyjal Summit - Archimonde (T6 Helm Token)", 33),
        "Shoulder": ("25-man Raid", "Black Temple - Mother Shahraz (T6 Shoulder Token)", 33),
        "Chest":    ("25-man Raid", "Black Temple - Illidan Stormrage (T6 Chest Token)", 33),
        "Hands":    ("25-man Raid", "Hyjal Summit - Azgalor (T6 Glove Token)", 33),
        "Legs":     ("25-man Raid", "Black Temple - The Illidari Council (T6 Leg Token)", 33),
        "Wrist":    ("25-man Raid", "Sunwell Plateau - Kalecgos (T6.5 Bracer Token)", 33),
        "Waist":    ("25-man Raid", "Sunwell Plateau - Brutallus (T6.5 Belt Token)", 33),
        "Feet":     ("25-man Raid", "Sunwell Plateau - Felmyst (T6.5 Boot Token)", 33),
    },
}

EFFORT_MAP = {
    "10-man Raid": 5.0,
    "25-man Raid": 6.0,
}


def main():
    print("Enriching tier set pieces with token drop sources...")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    updated = 0

    for tier_name, set_names, slot_bosses in [
        ("T4", T4_SETS, TIER_SLOT_BOSSES["T4"]),
        ("T5", T5_SETS, TIER_SLOT_BOSSES["T5"]),
        ("T6", T6_SETS, TIER_SLOT_BOSSES["T6"]),
    ]:
        tier_count = 0
        for set_name in set_names:
            for slot, (source_type, source_name, drop_rate) in slot_bosses.items():
                effort = EFFORT_MAP.get(source_type, 5.0)
                c.execute(
                    """UPDATE items
                       SET source_type=?, source_name=?, drop_rate=?, effort_score=?
                       WHERE set_name=? AND slot=?""",
                    (source_type, source_name, drop_rate, effort, set_name, slot),
                )
                tier_count += c.rowcount

        print(f"  {tier_name}: updated {tier_count} set pieces")
        updated += tier_count

    conn.commit()

    # Verify
    print(f"\n  Total: {updated} tier set pieces tagged")
    print("\n  Verification — sample set pieces:")
    for name in ["Voidheart Crown", "Voidheart Mantle", "Voidheart Robe",
                  "Cyclone Faceguard", "Cyclone Shoulderguards", "Cyclone Chestguard",
                  "Robe of the Corruptor", "Cowl of Tirisfal"]:
        c.execute("SELECT name, source_name FROM items WHERE name = ?", (name,))
        row = c.fetchone()
        if row:
            print(f"    {row[0]} → {row[1]}")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
