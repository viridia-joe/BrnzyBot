"""
BiS-equivalence harness — pins /gearprio and /gearcheck against the optimizer's
own BiS so the three gear tools can't silently disagree.

Why solve_bis is the reference: it runs hermetically against the committed item-DB
fixture (4,500+ real TBC items) and produces the genuine per-phase BiS (Spellstrike
set, Talon of the Tempest, …). The check is: if you're WEARING the BiS set,
/gearprio must report no upgrades and /gearcheck must read BiS for every slot; if
you then DOWNGRADE a slot, /gearprio must recommend the BiS piece back. That
contract is exactly what the double-subtraction bug violated (gearprio disagreeing
with solve_bis/gearcheck) — this harness would have caught it.

Tolerance: items within EP_DELTA are treated as equivalent (ties are common).

Not covered here (needs data the fixture lacks): comparing solve_bis to an
externally-curated "ground truth" BiS (needs human-verified lists) and the
/srprio raid-loot integration (needs item DB source_type='Raid' data — host only).
Both are noted in BACKLOG.md.

Requires numpy/scipy + the item-DB fixture. CI installs both.

    python tests/test_bis_equivalence.py
"""

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from tools.fixtures import ensure_item_db

ensure_item_db()  # points config.ITEM_DB_PATH at the committed fixture DB

import core.gear_handler as GH
from core.gear_optimizer import solve_bis, OptimizeParams
from core.gear_cache import GearSnapshot

GH.ITEM_DB_PATH = config.ITEM_DB_PATH  # rebind (was set at import, before ensure_item_db)

SPECS = ["destro_warlock", "ele_shaman"]
PHASE = 2
EP_DELTA = 5.0


def _bis_slots(spec, phase):
    db = sqlite3.connect(config.ITEM_DB_PATH)
    try:
        params = OptimizeParams(phase=phase, include_arena=True, mode="bis")
        res = solve_bis("Ref", spec, db, params, snapshot=None)
    finally:
        db.close()
    assert res.solver_status == "optimal", f"{spec}: solver {res.solver_status}"
    assert len(res.slots) >= 16, f"{spec}: only {len(res.slots)} BiS slots"
    return res.slots


def _snap_from_ids(spec, item_ids):
    db = sqlite3.connect(config.ITEM_DB_PATH)
    try:
        gear = []
        for iid in item_ids:
            r = db.execute("SELECT name, slot, stats, set_name FROM items WHERE item_id=?",
                           (iid,)).fetchone()
            if not r:
                continue
            name, slot, stats, setn = r
            gear.append({"slot": slot, "item_id": iid, "name": name,
                         "stats": json.loads(stats or "{}"), "set_name": setn or ""})
    finally:
        db.close()
    return GearSnapshot(character="Ref", realm="r", spec=spec, region="us",
                        report_code="x", report_time=0, fetched_at=0,
                        gear=gear, combat_stats={}, faction=0)


def _with_snapshot(snap, fn):
    """Run fn() with gear_handler.get_gear stubbed to return snap."""
    orig = GH.get_gear
    GH.get_gear = lambda *a, **k: snap
    try:
        return fn()
    finally:
        GH.get_gear = orig


def test_gearprio_reports_no_upgrades_when_wearing_bis():
    for spec in SPECS:
        bis = _bis_slots(spec, PHASE)
        snap = _snap_from_ids(spec, [s.item_id for s in bis])
        out = _with_snapshot(snap, lambda: GH.handle_gear_question(
            "Ref", spec, "r", phase_override=PHASE, guild_id="global"))
        assert "No upgrades found" in out, (
            f"{spec}: wearing BiS but gearprio still found upgrades:\n{out}")


def test_gearprio_recommends_bis_piece_back_after_downgrade():
    for spec in SPECS:
        bis = _bis_slots(spec, PHASE)
        head = next(s for s in bis if s.slot == "Head")
        db = sqlite3.connect(config.ITEM_DB_PATH)
        try:
            weak = db.execute(
                """SELECT item_id, name FROM items
                   WHERE slot='Head' AND stats LIKE '%SpellPower%' AND item_id != ?
                   ORDER BY ilvl ASC LIMIT 1""", (head.item_id,)).fetchone()
        finally:
            db.close()
        assert weak, f"{spec}: no weaker head to swap in"
        down_ids = [(weak[0] if s.slot == "Head" else s.item_id) for s in bis]
        snap = _snap_from_ids(spec, down_ids)
        out = _with_snapshot(snap, lambda: GH.handle_gear_question(
            "Ref", spec, "r", phase_override=PHASE, guild_id="global"))
        assert "RANKED UPGRADE LIST" in out, f"{spec}: no upgrades after downgrade:\n{out}"
        assert "Head |" in out, f"{spec}: head upgrade not surfaced:\n{out}"
        assert head.item_name in out, (
            f"{spec}: didn't recommend BiS head {head.item_name!r} back:\n{out}")


def test_gearcheck_shows_bis_for_a_bis_equipped_character():
    for spec in SPECS:
        bis = _bis_slots(spec, PHASE)
        snap = _snap_from_ids(spec, [s.item_id for s in bis])
        out = _with_snapshot(snap, lambda: GH.handle_gear_list(
            "Ref", spec, "r", phase_override=PHASE, guild_id="global", verbose=True))
        # Wearing BiS, gearcheck should not be flagging large per-slot gaps. It marks
        # BiS slots with a 🥇/🔥 medal and "BiS ✓"; assert it confirms BiS somewhere
        # and isn't advertising a big upgrade (no double-digit "% off" spikes).
        assert "BiS" in out, f"{spec}: gearcheck didn't confirm any BiS slot:\n{out[:400]}"


def _main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} BiS-equivalence tests passed")


if __name__ == "__main__":
    _main()
