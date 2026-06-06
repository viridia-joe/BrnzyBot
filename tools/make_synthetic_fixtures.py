"""
Generate a synthetic 'example log' that covers every TBC P1–P2 progression fight,
with a mixed raid that exercises each audit check:

  • enchant severity   — Pyra missing Legs (major→FAIL), Bulwark missing shield
  • empty sockets       — Pyra has an ungemmed socket (real 3-socket item)
  • green gems          — Pyra (1) and Stabby (2, →FAIL)
  • missing consumes    — Dotty has no weapon oil
  • potions             — counted from cast events (Pyra used none)
  • healer end-silence  — Mender goes quiet 65s before the kill (OOM indicator)

Writes WCL-shaped fixtures to tests/fixtures/wcl/ that core.wcl_client replays
when WCL_FIXTURE_DIR is set. Clearly synthetic (report code SYNTH…); real captures
from tools/capture_wcl.py drop in alongside and override by report code.

    python -m tools.make_synthetic_fixtures
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.fixtures import FIXTURE_WCL_DIR

CODE = "SYNTHLOG00000001"
DUR = 300_000  # 300s fights

PROGRESSION = [
    "Attumen the Huntsman", "Moroes", "Maiden of Virtue", "Opera Event", "The Curator",
    "Shade of Aran", "Terestian Illhoof", "Netherspite", "Nightbane", "Prince Malchezaar",
    "High King Maulgar", "Gruul the Dragonkiller", "Magtheridon",
    "Hydross the Unstable", "The Lurker Below", "Leotheras the Blind",
    "Fathom-Lord Karathress", "Morogrim Tidewalker", "Lady Vashj",
    "Al'ar", "Void Reaver", "High Astromancer Solarian", "Kael'thas Sunstrider",
]

# WCL gear array position by slot (mirrors core/audit/normalize.GEAR_SLOTS).
POS = {"Head": 0, "Shoulder": 2, "Chest": 4, "Waist": 5, "Legs": 6, "Feet": 7,
       "Wrist": 8, "Hands": 9, "Back": 14, "Main Hand": 15, "Off Hand": 16, "Relic": 17}

VEST, BELT = 21865, 21846        # real 3-socket / 2-socket items (for empty sockets)
GEN = "Frostbolt"; POTION = "Super Mana Potion"
AB_GEN, AB_POTION = 5000, 9001
META = {"caster": 34220, "healer": 32410, "phys": 32409, "tank": 32417}

# name, source_id, class, spec, meta-key, missing-enchants, (socket_item,[gem ilvls]),
# auras, potions, last-cast-ms
RAID = [
    ("Zappy",   1, "Shaman",  "ele_shaman",         "caster", [],
     (VEST, [70, 70, 70]), ["Blackened Basilisk", "Flask of Supreme Power", "Superior Wizard Oil"], 1, 298_000),
    ("Pyra",    2, "Mage",    "fire_mage",           "caster", ["Legs"],
     (VEST, [70, 60]),     ["Blackened Basilisk", "Flask of Pure Death", "Superior Wizard Oil"], 0, 298_000),
    ("Dotty",   3, "Warlock", "affliction_warlock",  "caster", [],
     (BELT, [70, 70]),     ["Blackened Basilisk", "Flask of Pure Death"], 1, 298_000),  # no oil
    ("Whisper", 4, "Priest",  "shadow_priest",       "caster", [],
     (BELT, [70, 70]),     ["Blackened Basilisk", "Flask of Pure Death", "Superior Wizard Oil"], 1, 298_000),
    ("Mender",  5, "Priest",  "holy_priest",         "healer", [],
     (BELT, [70, 70]),     ["Golden Fish Sticks", "Flask of Mighty Restoration", "Superior Mana Oil"], 1, 235_000),
    ("Leafy",   6, "Druid",   "resto_druid",         "healer", [],
     (BELT, [70, 70]),     ["Golden Fish Sticks", "Flask of Mighty Restoration", "Superior Mana Oil"], 1, 298_000),
    ("Bulwark", 7, "Warrior", "prot_warrior",        "tank",   ["Off Hand"],
     (VEST, [70, 70, 70]), ["Fisherman's Feast", "Flask of Fortification"], 1, 298_000),
    ("Stabby",  8, "Rogue",   "combat_rogue",        "phys",   [],
     (BELT, [60, 60]),     ["Grilled Mudfish", "Flask of Relentless Assault", "Adamantite Sharpening Stone"], 1, 298_000),
]


def _gem(ilvl):
    return {"id": 40000 + ilvl, "itemLevel": ilvl}


def _combatant(member):
    name, sid, cls, spec, metakey, miss, (sock_item, gem_ilvls), auras, _pot, _last = member
    from core.audit.profiles import get_profile
    prof = get_profile(spec)
    enchant_slots = [s for s in prof.enchantable_slots if s not in miss]

    gear = [{"id": 0} for _ in range(19)]
    for slot, pos in POS.items():
        gear[pos] = {"id": 30000 + pos, "itemLevel": 120, "quality": 4}
        if slot in enchant_slots:
            gear[pos]["permanentEnchant"] = 1000 + pos
    # meta gem lives in the head socket
    gear[0]["gems"] = [{"id": META[metakey], "itemLevel": 90}]
    # the real socketed item carries the scored gems (drives empty-socket detection)
    sock_pos = POS["Chest"] if sock_item == VEST else POS["Waist"]
    gear[sock_pos]["id"] = sock_item
    gear[sock_pos]["gems"] = [_gem(i) for i in gem_ilvls]
    return {"sourceID": sid, "gear": gear, "auras": [{"name": a} for a in auras]}


def _casts(member):
    *_, potions, last = member
    sid = member[1]
    out = [{"type": "cast", "sourceID": sid, "abilityGameID": AB_GEN, "timestamp": t}
           for t in range(0, last + 1, 15_000)]
    for t in [2_000, 150_000][:potions]:
        out.append({"type": "cast", "sourceID": sid, "abilityGameID": AB_POTION, "timestamp": t})
    return out


def main():
    os.makedirs(FIXTURE_WCL_DIR, exist_ok=True)

    def dump(name, obj):
        with open(os.path.join(FIXTURE_WCL_DIR, f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump(obj, f)

    ids = [m[1] for m in RAID]
    dump(f"{CODE}.actors", [{"id": m[1], "name": m[0], "subType": m[2]} for m in RAID])
    dump(f"{CODE}.fights", [
        {"id": i + 1, "name": boss, "kill": True, "startTime": 0, "endTime": DUR,
         "encounterID": 600 + i, "friendlyPlayers": ids}
        for i, boss in enumerate(PROGRESSION)
    ])
    dump(f"{CODE}.abilities", [
        {"gameID": AB_GEN, "name": GEN, "type": 1},
        {"gameID": AB_POTION, "name": POTION, "type": 1},
        {"gameID": 9002, "name": "Haste Potion", "type": 1},
    ])
    dump(f"{CODE}.specs", {m[0].lower(): m[3] for m in RAID})

    combatants = [_combatant(m) for m in RAID]
    casts = [c for m in RAID for c in _casts(m)]
    for fid in range(1, len(PROGRESSION) + 1):
        dump(f"{CODE}.combatant.{fid}", combatants)
        dump(f"{CODE}.casts.{fid}", casts)
    for m in RAID:
        dump(f"recent_reports.{m[0].lower()}", [{"code": CODE, "startTime": 1}])

    print(f"wrote synthetic fixtures for {CODE}: {len(PROGRESSION)} fights, "
          f"{len(RAID)} raiders → {FIXTURE_WCL_DIR}")


if __name__ == "__main__":
    main()
