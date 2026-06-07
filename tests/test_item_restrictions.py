"""
Item-restriction tests — class + weapon-proficiency validation in the optimizer's
candidate loader. Regression guard for the "arena Gavel (Mace) recommended to a
Warlock" bug: warlocks can't wield maces/axes/fists/polearms, but the loader only
checked armor type + class_restriction, never weapon_type.

Requires the item-DB fixture (4,500+ real items). CI installs deps.

    python tests/test_item_restrictions.py
"""

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from tools.fixtures import ensure_item_db

ensure_item_db()

from core.gear_optimizer import _load_candidates, OptimizeParams, WEAPON_SLOTS, REAL_WEAPON_TYPES


def _candidates(spec_key, phase=2):
    spec = json.load(open(os.path.join("data", "weights", f"{spec_key}.json")))
    db = sqlite3.connect(config.ITEM_DB_PATH)
    try:
        cands = _load_candidates(db, spec, OptimizeParams(phase=phase, include_arena=True,
                                                          mode="bis"), set())
        # attach weapon_type + class_restriction for assertions
        for c in cands:
            row = db.execute("SELECT weapon_type, class_restriction FROM items WHERE item_id=?",
                             (c["item_id"],)).fetchone()
            c["weapon_type"], c["class_restriction"] = row[0], row[1]
    finally:
        db.close()
    return spec, cands


def test_warlock_gets_no_illegal_weapons():
    spec, cands = _candidates("destro_warlock")
    allowed = set(spec["weapon_types"])              # Sword, Dagger, Staff, Wand
    illegal = [(c["name"], c["weapon_type"]) for c in cands
               if c["slot"] in WEAPON_SLOTS
               and c["weapon_type"] in REAL_WEAPON_TYPES
               and c["weapon_type"] not in allowed]
    assert not illegal, f"warlock offered weapons it can't wield: {illegal[:8]}"
    # sanity: the legal staff/daggers ARE still offered
    types_present = {c["weapon_type"] for c in cands if c["slot"] in WEAPON_SLOTS}
    assert "Staff" in types_present and "Dagger" in types_present
    assert "Mace" not in types_present and "Axe" not in types_present


def test_class_restricted_items_excluded():
    spec, cands = _candidates("destro_warlock")
    for c in cands:
        cr = json.loads(c["class_restriction"] or "[]")
        assert (not cr) or ("Warlock" in cr), f"{c['name']} restricted to {cr}, not Warlock"


def test_other_specs_keep_their_weapons():
    # ele_shaman must still be offered its allowed weapon types (no over-filtering).
    spec, cands = _candidates("ele_shaman")
    allowed = set(spec.get("weapon_types", []))
    present = {c["weapon_type"] for c in cands
               if c["slot"] in WEAPON_SLOTS and c["weapon_type"] in REAL_WEAPON_TYPES}
    assert present, "ele_shaman got no weapons at all (over-filtered)"
    assert present <= allowed, f"ele_shaman offered disallowed weapons: {present - allowed}"


def _names(spec_key, **params_kw):
    spec = json.load(open(os.path.join("data", "weights", f"{spec_key}.json")))
    db = sqlite3.connect(config.ITEM_DB_PATH)
    try:
        cands = _load_candidates(db, spec, OptimizeParams(phase=2, mode="bis", **params_kw), set())
    finally:
        db.close()
    return {c["name"] for c in cands}


def test_world_boss_gear_excluded_by_default():
    # Talon of the Tempest is a Doomwalker (world boss) drop. Source data is empty
    # so only the curated id list catches it; default include_world_boss is False.
    off = _names("destro_warlock", include_world_boss=False, include_arena=True)
    on  = _names("destro_warlock", include_world_boss=True,  include_arena=True)
    assert "Talon of the Tempest" not in off, "world-boss Talon leaked into candidates"
    assert "Talon of the Tempest" in on, "include_world_boss=True should restore it"


def test_arena_gear_excluded_when_opted_out():
    # source_type is empty so the SQL filter is a no-op; the name fallback handles it.
    off = _names("destro_warlock", include_arena=False, include_world_boss=True)
    on  = _names("destro_warlock", include_arena=True,  include_world_boss=True)
    gladiator_off = {n for n in off if "gladiator's" in n.lower()}
    gladiator_on  = {n for n in on  if "gladiator's" in n.lower()}
    assert not gladiator_off, f"arena gear leaked with arena off: {list(gladiator_off)[:5]}"
    assert gladiator_on, "arena gear should be present when arena is on"


def _main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} item-restriction tests passed")


if __name__ == "__main__":
    _main()
