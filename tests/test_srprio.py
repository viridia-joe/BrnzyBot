"""
Soft-Reserve Priority tests — raid resolver, candidate ranking, and the
empty-source DB diagnostic. The DB→instance source filter is validated on the
live item DB (fixtures carry no source data); here we test the pure logic.

    python tests/test_srprio.py    # plain-asserts (runs in CI)
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import srprio_handler as S


class _Hit:
    effective_weight = 0.0   # compute_item_ep multiplies SpellHit by this


def test_resolve_raid_aliases():
    assert S.resolve_raid("kara") == "karazhan"
    assert S.resolve_raid("KZ") == "karazhan"
    assert S.resolve_raid("Gruul's Lair") == "gruul"
    assert S.resolve_raid("ssc") == "ssc"
    assert S.resolve_raid("the eye") == "tk"
    assert S.resolve_raid("Magtheridon") == "magtheridon"
    assert S.resolve_raid("Karazhan") == "karazhan"
    assert S.resolve_raid("naxx") is None          # not a TBC raid in the set
    assert S.resolve_raid("") is None


def test_canon_slot_and_dual():
    assert S._canon_slot("Finger1") == "Ring"
    assert S._canon_slot("Trinket2") == "Trinket"
    assert S._canon_slot("Main Hand") == "Weapon"
    assert S._canon_slot("Two-Hand") == "Weapon"
    assert S._canon_slot("Head") == "Head"


def test_rank_orders_by_marginal_gain_and_filters_non_upgrades():
    spec_data = {"weights": {"HealingPower": 1.0, "Intellect": 0.5}}
    cands = [
        {"name": "Big Heal Chest", "slot": "Chest",  "stats": {"HealingPower": 100}, "source_name": "Karazhan - Curator"},
        {"name": "Tiny Ring",      "slot": "Finger1", "stats": {"HealingPower": 10},  "source_name": "Karazhan - Moroes"},
        {"name": "Worse Chest",    "slot": "Chest",   "stats": {"HealingPower": 20},  "source_name": "Karazhan - Attumen"},
    ]
    equipped = {"Chest": 40.0, "Ring": 5.0}
    out = S.rank_candidates(cands, equipped, spec_data, _Hit(), limit=5)
    names = [r["name"] for r in out]
    # Big Heal Chest: 100-40=60; Tiny Ring: 10-5=5; Worse Chest: 20-40<0 dropped
    assert names == ["Big Heal Chest", "Tiny Ring"]
    assert out[0]["gain"] == 60.0


def test_rank_dedupes_and_limits_to_five():
    spec_data = {"weights": {"HealingPower": 1.0}}
    cands = [{"name": f"Item{i}", "slot": "Chest", "stats": {"HealingPower": 100 + i},
              "source_name": "Karazhan - Boss"} for i in range(8)]
    cands.append({"name": "Item0", "slot": "Chest", "stats": {"HealingPower": 999},  # dup name
                  "source_name": "Karazhan - Boss"})
    out = S.rank_candidates(cands, {"Chest": 0.0}, spec_data, _Hit(), limit=5)
    assert len(out) == 5
    assert len({r["name"] for r in out}) == 5          # no dup
    assert out[0]["name"] == "Item7"                    # highest stat first


def test_boss_extraction():
    assert S._boss_of("Karazhan - Moroes", "Karazhan") == "Moroes"
    assert S._boss_of("Karazhan", "Karazhan") == "Karazhan"


def test_load_candidates_empty_on_sourceless_db():
    """The fixture/real-empty DB has no source data → no candidates (drives the
    'no loot found' diagnostic rather than a crash)."""
    from tools.fixtures import ensure_item_db
    ensure_item_db()
    import config
    db = sqlite3.connect(config.ITEM_DB_PATH)
    try:
        cands = S._load_raid_candidates(db, "karazhan",
                                        {"class": "Shaman", "armor_types": ["Mail"]}, 5)
    finally:
        db.close()
    assert cands == []


def _main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} srprio tests passed")


if __name__ == "__main__":
    _main()
