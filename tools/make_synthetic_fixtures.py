"""
Generate a synthetic 'example log' covering every TBC P1–P2 progression fight,
with a mixed raid that exercises every audit check. Uses REAL item/gem ids (from
the committed DBs) so the item-DB-backed checks (empty sockets, meta socket, gem
color/quality, meta activation) evaluate truthfully:

  • enchant severity   — Pyra missing Legs (major→FAIL), Bulwark missing shield
  • empty sockets       — Pyra (real 3-socket item, one ungemmed)
  • green gems          — Pyra (1), Stabby (2)
  • missing meta        — Dotty has a meta socket but no meta gem
  • INACTIVE meta       — Stabby's meta has 0 blue gems (requirement unmet)
  • missing consumes    — Dotty has no weapon oil
  • potions             — counted from cast events (Pyra used none)
  • healer end-silence  — Mender goes quiet before the kill (OOM indicator)

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

# Real ids from the committed DBs (so colors/sockets/quality resolve authoritatively).
HELM = 24545                 # has sockets [Meta, Yellow]
VEST, BELT = 21865, 21846    # 3-socket / 2-socket bodies (empty-socket detection)
BLUE, BLUE_G = 24033, 23118  # Solid Star of Elune (rare) / Solid Azure Moonstone (green)
RED, RED_G = 24027, 23094    # Bold Living Ruby (rare) / Teardrop Blood Garnet (green)
METAC, METAH, METAP, METAT = 34220, 25901, 32409, 25896  # caster/healer/phys/tank meta
GEN, POTION = "Frostbolt", "Super Mana Potion"
AB_GEN, AB_POTION = 5000, 9001

# name, sid, class, spec, missing-enchants, head_gems, body_item, body_gems, auras, potions, last
RAID = [
    ("Zappy",   1, "Shaman",  "ele_shaman",        [],          [METAC, BLUE], VEST, [BLUE, RED, RED],
     ["Blackened Basilisk", "Flask of Supreme Power", "Superior Wizard Oil"], 1, 298_000),
    ("Pyra",    2, "Mage",    "fire_mage",          ["Legs"],    [METAC, BLUE], VEST, [BLUE_G, RED],
     ["Blackened Basilisk", "Flask of Pure Death", "Superior Wizard Oil"], 0, 298_000),
    ("Dotty",   3, "Warlock", "affliction_warlock", [],          [BLUE],        BELT, [BLUE, RED],
     ["Blackened Basilisk", "Flask of Pure Death"], 1, 298_000),                       # no oil; no meta gem
    ("Whisper", 4, "Priest",  "shadow_priest",      [],          [METAC, BLUE], BELT, [BLUE, RED],
     ["Blackened Basilisk", "Flask of Pure Death", "Superior Wizard Oil"], 1, 298_000),
    ("Mender",  5, "Priest",  "holy_priest",        [],          [METAH, BLUE], BELT, [BLUE, RED],
     ["Golden Fish Sticks", "Flask of Mighty Restoration", "Superior Mana Oil"], 1, 235_000),
    ("Leafy",   6, "Druid",   "resto_druid",        [],          [METAH, BLUE], BELT, [BLUE, RED],
     ["Golden Fish Sticks", "Flask of Mighty Restoration", "Superior Mana Oil"], 1, 298_000),
    ("Bulwark", 7, "Warrior", "prot_warrior",       ["Off Hand"],[METAT, BLUE], VEST, [BLUE, RED, RED],
     ["Fisherman's Feast", "Flask of Fortification"], 1, 298_000),
    ("Stabby",  8, "Rogue",   "combat_rogue",       [],          [METAP, RED],  BELT, [RED_G, RED_G],
     ["Grilled Mudfish", "Flask of Relentless Assault", "Adamantite Sharpening Stone"], 1, 298_000),
]


def _combatant(member):
    from core.audit.profiles import get_profile
    name, sid, cls, spec, miss, head_gems, body_item, body_gems, auras, _pot, _last = member
    enchant_slots = [s for s in get_profile(spec).enchantable_slots if s not in miss]

    gear = [{"id": 0} for _ in range(19)]
    for slot, pos in POS.items():
        gear[pos] = {"id": 30000 + pos, "itemLevel": 120, "quality": 4}
        if slot in enchant_slots:
            gear[pos]["permanentEnchant"] = 1000 + pos
    def real(pos, slot, item_id, gem_ids):
        e = {"id": item_id, "itemLevel": 120, "quality": 4,
             "gems": [{"id": g} for g in gem_ids]}
        if slot in enchant_slots:        # keep the enchant we'd otherwise overwrite
            e["permanentEnchant"] = 1000 + pos
        gear[pos] = e

    real(POS["Head"], "Head", HELM, head_gems)
    bslot = "Chest" if body_item == VEST else "Waist"
    real(POS[bslot], bslot, body_item, body_gems)
    # Emit a stat block consistent with the intended spec's role so that the
    # log-based spec detector (gear_cache.spec_from_stats) recovers this spec —
    # TBC Anniversary logs carry no specID, so role is read from these stats.
    role_stats = _stats_for_spec(spec)
    return {"sourceID": sid, "gear": gear,
            "auras": [{"name": a} for a in auras], **role_stats}


def _stats_for_spec(spec: str) -> dict:
    """A minimal stat block that makes spec_from_stats land on `spec`."""
    healer = {"intellect": 500, "spirit": 400, "critSpell": 80, "strength": 50,
              "agility": 50, "armor": 6000, "stamina": 600, "block": 0}
    caster_dps = {"intellect": 520, "spirit": 150, "critSpell": 300, "strength": 50,
                  "agility": 60, "armor": 6000, "stamina": 650, "block": 0}
    melee = {"strength": 700, "agility": 200, "intellect": 60, "spirit": 90,
             "critSpell": 0, "armor": 10000, "stamina": 750, "block": 0}
    tank = {"strength": 400, "agility": 150, "intellect": 60, "spirit": 90,
            "critSpell": 0, "armor": 16000, "stamina": 1100, "block": 30}
    if spec.startswith(("holy_", "resto_")):
        return healer
    if spec.startswith("prot_") or spec == "feral_bear_druid":
        return tank
    if spec in ("ele_shaman", "balance_druid", "shadow_priest") or "mage" in spec or "warlock" in spec:
        return caster_dps
    return melee


def _casts(member):
    sid, potions, last = member[1], member[-2], member[-1]
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
    ])
    dump(f"{CODE}.specs", {m[0].lower(): m[3] for m in RAID})

    combatants = [_combatant(m) for m in RAID]
    casts = [c for m in RAID for c in _casts(m)]
    for fid in range(1, len(PROGRESSION) + 1):
        dump(f"{CODE}.combatant.{fid}", combatants)
        dump(f"{CODE}.casts.{fid}", casts)
    # Per-character fixtures so /gearcheck + auto-register replay too.
    classid = {"Warrior": 1, "Paladin": 2, "Hunter": 3, "Rogue": 4, "Priest": 5,
               "Shaman": 7, "Mage": 8, "Warlock": 9, "Druid": 11}
    for m, combatant in zip(RAID, combatants):
        name, sid, cls = m[0], m[1], m[2]
        dump(f"recent_reports.{name.lower()}", [{"code": CODE, "startTime": 1}])
        dump(f"character.{name.lower()}", {"classID": classid.get(cls, 0),
                                           "name": name, "reports": [{"code": CODE, "startTime": 1}]})
        dump(f"{CODE}.combatant.src.{sid}", [combatant])

    print(f"wrote synthetic fixtures for {CODE}: {len(PROGRESSION)} fights, "
          f"{len(RAID)} raiders → {FIXTURE_WCL_DIR}")


if __name__ == "__main__":
    main()
