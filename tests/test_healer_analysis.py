"""
Healer analysis tests — gear-based throughput/regen block for /gearcheck.

No network, no item DB: analyze_healer reads stats straight off the snapshot's
equipped-gear list, so we build tiny fake snapshots.

    python tests/test_healer_analysis.py    # plain-asserts (runs in CI)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import healer_analysis as H


class _Snap:
    def __init__(self, gear, combat_stats=None):
        self.gear = gear
        self.combat_stats = combat_stats or {}


def _item(**stats):
    return {"slot": "Chest", "item_id": 1, "name": "x", "stats": stats, "set_name": None}


def test_is_healer():
    assert H.is_healer("resto_shaman")
    assert H.is_healer("holy_paladin")
    assert not H.is_healer("ele_shaman")
    assert not H.is_healer("_conversions")   # data keys aren't specs


def test_non_healer_returns_none():
    assert H.analyze_healer("fire_mage", _Snap([_item(HealingPower=100)])) is None


def test_no_gear_returns_none():
    assert H.analyze_healer("resto_shaman", _Snap([])) is None


def test_healing_uses_healingpower_then_spellpower_fallback():
    # One item lists HealingPower, another only SpellPower → both count once each.
    snap = _Snap([_item(HealingPower=800), _item(SpellPower=500)])
    out = H.analyze_healer("resto_shaman", snap)
    assert out is not None
    assert "+Healing: **1,300**" in out
    # A spell-damage item listing BOTH must not double-count (per-item fallback).
    snap2 = _Snap([_item(HealingPower=23, SpellPower=23)])
    out2 = H.analyze_healer("resto_shaman", snap2)
    assert "+Healing: **23**" in out2


def test_mana_pool_from_base_plus_intellect():
    # resto_shaman base_mana 3835; 400 Int * 15 = 6000 → 9835
    snap = _Snap([_item(Intellect=400)])
    out = H.analyze_healer("resto_shaman", snap)
    assert "Mana pool: **9,835**" in out


def test_tier_thresholds_healing():
    # resto_shaman healing band: 1200 / 1500 / 1800
    assert "❌" in H.analyze_healer("resto_shaman", _Snap([_item(HealingPower=900)]))
    assert "🟡" in H.analyze_healer("resto_shaman", _Snap([_item(HealingPower=1300)]))
    assert "✅" in H.analyze_healer("resto_shaman", _Snap([_item(HealingPower=1600)]))
    assert "🌟" in H.analyze_healer("resto_shaman", _Snap([_item(HealingPower=1900)]))


def test_crit_prefers_combat_stats_rating():
    # critSpell rating 44.16 / 22.08 = 2.0%
    snap = _Snap([_item(HealingPower=1500, SpellCrit=999)], combat_stats={"critSpell": 44.16})
    out = H.analyze_healer("resto_shaman", snap)
    assert "crit (gear/rating): 2.0%" in out


def test_all_four_healer_specs_render():
    snap = _Snap([_item(HealingPower=1500, MP5=60, Spirit=120, Intellect=350)])
    for spec in ("resto_shaman", "holy_paladin", "holy_priest", "resto_druid"):
        out = H.analyze_healer(spec, snap)
        assert out and "Healer Analysis" in out, f"{spec} produced no block"


def _main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} healer-analysis tests passed")


if __name__ == "__main__":
    _main()
