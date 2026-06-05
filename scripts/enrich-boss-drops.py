#!/usr/bin/env python3
"""
Enrich item database with boss drop sources using known TBC loot tables.
Maps item IDs to their source boss/dungeon.

This is a static mapping — TBC loot tables don't change.
"""

import json
import os
import sqlite3

DB_PATH = os.path.expanduser("~/.openclaw/data/tbc_items.db")

# TBC Raid & Dungeon Loot Tables
# Format: (source_type, source_name, drop_rate, [item_ids])
LOOT_TABLES = [
    # === KARAZHAN (10-man) ===
    ("10-man Raid", "Karazhan - Attumen the Huntsman", 15, [
        28477, 28478, 28479, 28480, 28481, 28454, 28453, 28462, 28463,
        28468, 28545, 28472, 28473, 28474, 28475, 28476,
    ]),
    ("10-man Raid", "Karazhan - Moroes", 15, [
        28529, 28528, 28530, 28525, 28524, 28527, 28526, 28523, 28522,
        28521, 28567, 28570, 28569, 28566, 28565, 28568,
    ]),
    ("10-man Raid", "Karazhan - Maiden of Virtue", 15, [
        28511, 28515, 28517, 28514, 28516, 28512, 28519, 28518, 28520,
        28510, 28513, 28508,
    ]),
    ("10-man Raid", "Karazhan - Opera Event", 15, [
        28578, 28579, 28580, 28581, 28582, 28583, 28584, 28585, 28586,
        28587, 28588, 28589, 28590, 28591, 28592, 28593, 28594, 28572,
        28573, 28574, 28575, 28576, 28577,
    ]),
    ("10-man Raid", "Karazhan - The Curator", 15, [
        28612, 28609, 28633, 28631, 28647, 28621, 28649, 28634, 28644,
        28610, 29757,
    ]),
    ("10-man Raid", "Karazhan - Shade of Aran", 15, [
        28670, 28666, 28672, 28671, 28673, 28669, 28667, 28726, 28674,
        28668, 28663, 28662, 28660, 28661, 28664, 28665,
    ]),
    ("10-man Raid", "Karazhan - Terestian Illhoof", 15, [
        28785, 28789, 28790, 28792, 28786, 28787, 28788, 28791,
    ]),
    ("10-man Raid", "Karazhan - Netherspite", 15, [
        28743, 28744, 28745, 28746, 28747, 28748, 28749, 28750, 28751,
        28752,
    ]),
    ("10-man Raid", "Karazhan - Nightbane", 15, [
        28601, 28602, 28603, 28604, 28606, 28608, 28611,
    ]),
    ("10-man Raid", "Karazhan - Prince Malchezaar", 15, [
        28755, 28756, 28757, 28758, 28759, 28760, 28761, 28762, 28763,
        28764, 28765, 28766, 28767, 28768, 28770, 28771, 28772, 28773,
        # T4 helm tokens
        29760, 29761, 29759,
    ]),
    ("10-man Raid", "Karazhan - Trash Drop", 10, [
        28454, 30642, 30643, 30644, 30668,
    ]),

    # === GRUUL'S LAIR (25-man) ===
    ("25-man Raid", "Gruul's Lair - High King Maulgar", 15, [
        28794, 28795, 28796, 28797, 28799, 28800, 28801,
        # T4 shoulder tokens
        29762, 29763, 29764,
    ]),
    ("25-man Raid", "Gruul's Lair - Gruul the Dragonkiller", 15, [
        28810, 28822, 28823, 28824, 28825, 28826, 28827, 28828, 28830,
        # T4 leg tokens
        29765, 29766, 29767,
    ]),

    # === MAGTHERIDON'S LAIR (25-man) ===
    ("25-man Raid", "Magtheridon's Lair - Magtheridon", 15, [
        28774, 28775, 28776, 28777, 28778, 28779, 28780, 28781, 28782, 28783,
        29458, 29456, 29457,
        # T4 chest tokens
        29753, 29754, 29755,
    ]),

    # === SSC (25-man, Phase 2) ===
    ("25-man Raid", "SSC - Hydross the Unstable", 15, [
        30048, 30050, 30051, 30052, 30053, 30054, 30055, 30056,
    ]),
    ("25-man Raid", "SSC - The Lurker Below", 15, [
        30057, 30058, 30059, 30060, 30061, 30062, 30063, 30064, 30065,
    ]),
    ("25-man Raid", "SSC - Leotheras the Blind", 15, [
        30087, 30088, 30089, 30090, 30091, 30092, 30093,
    ]),
    ("25-man Raid", "SSC - Fathom-Lord Karathress", 15, [
        30094, 30095, 30096, 30097, 30098, 30099, 30100, 30101,
    ]),
    ("25-man Raid", "SSC - Morogrim Tidewalker", 15, [
        30005, 30006, 30007, 30008, 30009, 30010, 30023, 30024, 30025,
    ]),
    ("25-man Raid", "SSC - Lady Vashj", 15, [
        30102, 30103, 30104, 30105, 30106, 30107, 30108, 30109, 30110, 30111,
        # T5 helm tokens
        30243, 30244, 30242,
    ]),

    # === TEMPEST KEEP (25-man, Phase 2) ===
    ("25-man Raid", "TK - Al'ar", 15, [
        29918, 29919, 29920, 29921, 29922, 29923, 29924, 29925,
    ]),
    ("25-man Raid", "TK - Void Reaver", 15, [
        29983, 29984, 29985, 29986, 29987, 29988, 29989, 29990,
        # T5 shoulder tokens
        30248, 30249, 30250,
    ]),
    ("25-man Raid", "TK - High Astromancer Solarian", 15, [
        29962, 29963, 29964, 29965, 29966, 29967, 29968, 29969, 29970, 29971,
    ]),
    ("25-man Raid", "TK - Kael'thas Sunstrider", 15, [
        29977, 29978, 29979, 29980, 29981, 29982, 29947, 29948, 29949,
        29950, 29951, 29996, 29993, 29994, 29995, 29997, 29998, 29999,
        30000, 30001, 30002, 30003, 30004,
        # T5 chest tokens
        30236, 30237, 30238,
    ]),

    # === WORLD BOSSES ===
    ("World Boss", "Doomwalker", 15, [
        30722, 30723, 30724, 30725, 30726, 30727, 30728, 30729,
    ]),
    ("World Boss", "Doom Lord Kazzak", 15, [
        30730, 30731, 30732, 30733, 30734, 30735, 30736, 30737,
    ]),

    # === BADGE VENDOR ===
    ("Badge", "G'eras - 25 Badges of Justice", 100, [
        29383, 29384, 29385, 29386, 29382,
    ]),
    ("Badge", "G'eras - 33 Badges of Justice", 100, [
        29368, 29369, 29367, 29366, 29365,
    ]),
    ("Badge", "G'eras - 35 Badges of Justice", 100, [
        29373, 29374, 29375, 29372, 29371,
    ]),
    ("Badge", "G'eras - 41 Badges of Justice", 100, [
        29370, 29376, 29377, 29378, 29379,
    ]),
    ("Badge", "G'eras - 50 Badges of Justice", 100, [
        33296, 33291, 33292, 33293, 33294, 33295,
        33297, 33298, 33299, 33300, 33301,
    ]),

    # === HEROIC DUNGEON FINAL BOSSES ===
    ("Heroic Dungeon", "H Ramparts - Nazan & Vazruden", 15, [28182, 28176, 28174, 28187, 28184]),
    ("Heroic Dungeon", "H Blood Furnace - Keli'dan", 15, [28266, 28269, 28267, 28268, 28270]),
    ("Heroic Dungeon", "H Slave Pens - Quagmirran", 15, [27796, 27806, 27800, 27742, 27712]),
    ("Heroic Dungeon", "H Underbog - The Black Stalker", 15, [27907, 27896, 27897, 27899, 27898]),
    ("Heroic Dungeon", "H Mana-Tombs - Nexus-Prince Shaffar", 15, [28400, 27843, 27844, 27845, 27846]),
    ("Heroic Dungeon", "H Auchenai Crypts - Exarch Maladaar", 15, [27871, 27872, 27869, 27870, 27867]),
    ("Heroic Dungeon", "H Sethekk Halls - Talon King Ikiss", 15, [27919, 27918, 27917, 27916, 27915]),
    ("Heroic Dungeon", "H Shadow Labyrinth - Murmur", 15, [27911, 27912, 27913, 27914, 27910]),
    ("Heroic Dungeon", "H Mechanar - Pathaleon", 15, [28278, 28285, 28284, 28282, 28286]),
    ("Heroic Dungeon", "H Botanica - Warp Splinter", 15, [28370, 28371, 28372, 28367, 28373]),
    ("Heroic Dungeon", "H Arcatraz - Harbinger Skyriss", 15, [28406, 28411, 28415, 28413, 28414]),
    ("Heroic Dungeon", "H Steamvault - Warlord Kalithresh", 15, [27508, 27510, 27509, 27511, 27512]),
    ("Heroic Dungeon", "H Shattered Halls - Warchief Kargath", 15, [27528, 27527, 27529, 27524, 27526]),
    ("Heroic Dungeon", "H Old Hillsbrad - Epoch Hunter", 15, [28191, 28190, 28187, 28192, 28193]),
    ("Heroic Dungeon", "H Black Morass - Aeonus", 15, [28193, 28227, 28228, 28226, 28229]),

    # === CRAFTED ===
    ("Crafted", "Tailoring (Spellstrike)", 100, [24266, 24262]),
    ("Crafted", "Tailoring (Frozen Shadoweave)", 100, [21871, 21870, 21869]),
    ("Crafted", "Tailoring (Spellfire)", 100, [21848, 21847, 21846]),
    ("Crafted", "Tailoring (Girdle of Ruination)", 100, [24256]),
    ("Crafted", "Tailoring (Belt of Blasting)", 100, [24257]),
    ("Crafted", "Tailoring (Bracers of Havok)", 100, [24253]),
    ("Crafted", "Tailoring (Battlecast set)", 100, [24264, 24261, 24260]),
    ("Crafted", "Leatherworking (Netherstrike)", 100, [29515, 29517, 29516]),
    ("Crafted", "Leatherworking (Windhawk)", 100, [29524, 29522, 29523]),
    ("Crafted", "Engineering (Goggles)", 100, [32461, 32472, 32473, 32474, 32475, 32476, 34847, 34848, 34849, 34851, 35182, 35185]),

    # === OGRI'LA / SKYGUARD DAILIES (Phase 2) ===
    # The WowSims re-import brings these in with phase=2; with an empty source_type
    # they are already BiS-eligible, so this entry only adds the source label.
    # IDs left to a DB audit so we never mislabel — fill from:
    #   SELECT item_id, name FROM items WHERE phase=2 AND source_type='';
    ("Quest", "Ogri'la / Skyguard Dailies", 100, [
        # TODO(verify): populate from the rebuilt DB.
    ]),
]

# Sources applied by item-NAME prefix rather than by enumerating IDs. The PvP
# arena sets follow a strict "<Season Title> Gladiator's ..." naming convention,
# so a prefix match labels every piece (armor, jewelry, weapons, off-pieces)
# comprehensively without a hand-maintained ID list.
# Format: (source_type, source_name, effort_score, name_prefix)
NAME_PREFIX_SOURCES = [
    ("Arena", "Season 2 Arena (Merciless Gladiator)", 4.0, "Merciless Gladiator's "),
    ("Arena", "Season 1 Arena (Gladiator)",           4.0, "Gladiator's "),
]


def main():
    print("Enriching database with boss drop loot tables...")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    effort_map = {
        "10-man Raid": 5.0,
        "25-man Raid": 6.0,
        "World Boss": 9.0,
        "Heroic Dungeon": 3.0,
        "Badge": 2.5,
        "Crafted": 3.0,
        "Arena": 4.0,
        "Quest": 2.0,
    }

    updated = 0
    for source_type, source_name, drop_rate, item_ids in LOOT_TABLES:
        effort = effort_map.get(source_type, 5.0)
        for item_id in item_ids:
            c.execute(
                "UPDATE items SET source_type=?, source_name=?, drop_rate=?, effort_score=? WHERE item_id=? AND (source_type = '' OR source_type = 'Unknown')",
                (source_type, source_name, drop_rate, effort, item_id),
            )
            if c.rowcount > 0:
                updated += 1

    # Name-prefix sources (PvP arena sets) — only touches still-unclassified rows.
    prefix_updated = 0
    for source_type, source_name, effort, name_prefix in NAME_PREFIX_SOURCES:
        c.execute(
            "UPDATE items SET source_type=?, source_name=?, drop_rate=?, effort_score=? "
            "WHERE name LIKE ? AND (source_type = '' OR source_type = 'Unknown')",
            (source_type, source_name, 100, effort, name_prefix + "%"),
        )
        prefix_updated += c.rowcount
    updated += prefix_updated

    conn.commit()

    # Report
    c.execute("SELECT source_type, COUNT(*) FROM items WHERE source_type != '' AND source_type != 'Unknown' GROUP BY source_type ORDER BY COUNT(*) DESC")
    print(f"\n  Updated {updated} items from loot tables ({prefix_updated} via name prefix)")
    print("  Classified source distribution:")
    for row in c.fetchall():
        print(f"    {row[0]}: {row[1]}")

    c.execute("SELECT COUNT(*) FROM items WHERE source_type = '' OR source_type = 'Unknown'")
    print(f"  Still unclassified: {c.fetchone()[0]}")

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
