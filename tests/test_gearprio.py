"""
/gearprio upgrade-entry tests — the regression guard for the "always at BiS" bug.

The optimizer reports a swap's SlotResult.ep as the MARGINAL gain over the equipped
item. _build_upgrade_priority once did `sr.ep - cur_ep`, subtracting the equipped EP
a second time, so an upgrade only surfaced if worth DOUBLE the equipped item —
hiding nearly every real upgrade (e.g. brnz's missing BiS cloak/shoulders read as
"at or near BiS"). These tests pin the corrected marginal-gain semantics.

Requires numpy/scipy (gear_handler imports gear_optimizer). CI installs them.

    python tests/test_gearprio.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.gear_handler import _upgrade_entries
from core.gear_optimizer import SlotResult


class _Ctx:
    def __init__(self, gear_summary, set_costs=None):
        self.gear_summary = gear_summary
        self._set_costs = set_costs or {}

    def set_bonus_cost(self, set_name):
        return self._set_costs.get(set_name, 0.0)


class _Snap:
    def __init__(self, gear):
        self.gear = gear


def _equipped(name, set_name=""):
    return {"name": name, "set_name": set_name}


def test_marginal_gain_surfaces_upgrade():
    """The core bug: a +30 EP cloak over a 50 EP cloak must show as +30, not -20."""
    ctx = _Ctx([{"slot": "Back", "name": "Old Cloak", "ep": 50.0, "set_name": ""}])
    snap = _Snap([_equipped("Old Cloak")])
    slots = [
        SlotResult(slot="Back", item_id=2, item_name="BiS Cloak", ep=30.0,
                   set_name="", source="Karazhan - Curator", was_equipped=False, phase=1),
        SlotResult(slot="Head", item_id=3, item_name="Worn Hat", ep=40.0,
                   set_name="", source="", was_equipped=True, phase=1),
    ]
    entries = _upgrade_entries(slots, ctx, snap)
    assert len(entries) == 1, "the cloak upgrade was dropped (the regression)"
    e = entries[0]
    assert e.to_name == "BiS Cloak"
    assert e.from_name == "Old Cloak"
    assert e.net_ep == 30.0          # marginal gain, NOT 30 - 50 = -20
    assert e.to_ep == 80.0           # 50 equipped + 30 gain → absolute, for display
    assert e.rank == 1


def test_equipped_items_are_not_recommended():
    ctx = _Ctx([{"slot": "Chest", "name": "Tier Chest", "ep": 70.0, "set_name": "Voidheart"}])
    snap = _Snap([_equipped("Tier Chest", "Voidheart")])
    slots = [SlotResult(slot="Chest", item_id=1, item_name="Tier Chest", ep=70.0,
                        set_name="Voidheart", source="", was_equipped=True, phase=2)]
    assert _upgrade_entries(slots, ctx, snap) == []


def test_set_cost_can_gate_a_marginal_upgrade():
    """A tiny gain that costs a set bonus to break should be filtered out."""
    ctx = _Ctx([{"slot": "Hands", "name": "Tier Gloves", "ep": 60.0, "set_name": "Voidheart"}],
               set_costs={"Voidheart": 25.0})
    snap = _Snap([_equipped("Tier Gloves", "Voidheart")])
    slots = [SlotResult(slot="Hands", item_id=5, item_name="Off-set Gloves", ep=10.0,
                        set_name="", source="", was_equipped=False, phase=2)]
    # raw gain 10, minus 25 set-break cost = -15 → not recommended
    assert _upgrade_entries(slots, ctx, snap) == []


def test_dual_slot_compares_against_weaker_ring():
    ctx = _Ctx([
        {"slot": "Ring", "name": "Strong Ring", "ep": 60.0, "set_name": ""},
        {"slot": "Ring", "name": "Weak Ring",   "ep": 30.0, "set_name": ""},
    ])
    snap = _Snap([_equipped("Strong Ring"), _equipped("Weak Ring")])
    slots = [SlotResult(slot="Ring", item_id=9, item_name="New Ring", ep=15.0,
                        set_name="", source="", was_equipped=False, phase=2)]
    entries = _upgrade_entries(slots, ctx, snap)
    assert len(entries) == 1
    assert entries[0].from_name == "Weak Ring"   # you replace the weaker piece
    assert entries[0].net_ep == 15.0


def test_entries_sorted_by_net_ep_desc():
    ctx = _Ctx([
        {"slot": "Back",     "name": "Old Cloak", "ep": 50.0, "set_name": ""},
        {"slot": "Shoulder", "name": "Old Pads",  "ep": 50.0, "set_name": ""},
    ])
    snap = _Snap([_equipped("Old Cloak"), _equipped("Old Pads")])
    slots = [
        SlotResult(slot="Back",     item_id=2, item_name="Cloak+10", ep=10.0,
                   set_name="", source="", was_equipped=False, phase=2),
        SlotResult(slot="Shoulder", item_id=3, item_name="Pads+40",  ep=40.0,
                   set_name="", source="", was_equipped=False, phase=2),
    ]
    entries = _upgrade_entries(slots, ctx, snap)
    assert [e.to_name for e in entries] == ["Pads+40", "Cloak+10"]
    assert [e.rank for e in entries] == [1, 2]


def _main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} gearprio tests passed")


if __name__ == "__main__":
    _main()
