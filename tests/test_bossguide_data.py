"""
Guards the unified strategy/bossguide store (docs/PHASE_READINESS.md §2).

Boss content lives once in data/strategy/*.json: /strat reads the FTS DB built
from those files, /bossguide reads their optional `bossguide` blocks. These tests
pin that contract so SSC stays wired and TK stays bossguide-only.

    python tests/test_bossguide_data.py
"""

import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build_strategy_db as B
from core import bossguide_data as BG
from core.fight_diagrams import canonical_path  # diagrams are keyed by boss slug

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STRAT_DIR = os.path.join(_ROOT, "data", "strategy")

_SSC = ["hydross", "lurker", "morogrim", "karathress", "leotheras", "vashj"]
_TK = ["alar", "voidreaver", "solarian", "kaelthas"]


def _build_db():
    db = os.path.join(tempfile.mkdtemp(), "strategy.db")
    B.build(db, _STRAT_DIR)
    return sqlite3.connect(db)


def test_bossguide_loads_ssc_and_tk_from_json():
    # No hardcoded dict anymore — all 10 come from the data files.
    for key in _SSC + _TK:
        assert key in BG.BOSS_DATA, f"{key} missing from BOSS_DATA"
    assert BG.BOSS_DATA["hydross"].raid == "SSC"
    assert BG.BOSS_DATA["kaelthas"].raid == "TK"


def test_display_order_is_phase_raid_bossnum():
    keys = [k for k, _ in BG.BOSS_DISPLAY_ORDER]
    # SSC (boss 1..6) before TK (boss 1..4)
    assert keys[:6] == _SSC, keys
    assert keys[6:10] == _TK, keys


def test_resolve_boss_aliases():
    assert BG.resolve_boss("hyd") == "hydross"
    assert BG.resolve_boss("lady vashj") == "vashj"
    assert BG.resolve_boss("kael") == "kaelthas"
    assert BG.resolve_boss("nonsense-boss") is None


def test_leotheras_demon_tank_is_fire_not_shadow():
    # Regression guard for the corrected hallucination: Chaos Blast is FIRE.
    ctx = BG.BOSS_DATA["leotheras"].context.lower()
    assert "fire resistance" in ctx
    assert "shadow resist" not in ctx


def test_strat_fts_indexes_ssc_but_not_tk():
    conn = _build_db()
    ssc_n = conn.execute(
        "SELECT COUNT(*) FROM bosses WHERE zone_slug='serpentshrine_cavern'"
    ).fetchone()[0]
    tk_n = conn.execute(
        "SELECT COUNT(*) FROM bosses WHERE zone_slug='tempest_keep'"
    ).fetchone()[0]
    assert ssc_n == 6, f"expected 6 SSC bosses in /strat, got {ssc_n}"
    assert tk_n == 0, "TK should be strat_index=false (bossguide-only)"


def test_strat_fts_search_finds_ssc_content():
    conn = _build_db()
    hit = conn.execute(
        "SELECT b.name FROM bosses b JOIN bosses_fts f ON b.boss_id=f.rowid "
        "WHERE bosses_fts MATCH 'hydross'"
    ).fetchall()
    assert ("Hydross the Unstable",) in hit
    ab = conn.execute(
        "SELECT b.name FROM abilities a JOIN abilities_fts af ON a.ability_id=af.rowid "
        "JOIN bosses b ON a.boss_id=b.boss_id WHERE abilities_fts MATCH 'tainted core'"
    ).fetchall()
    assert ("Lady Vashj",) in ab


def test_diagram_keys_match_boss_slugs():
    # has_diagram bosses must use a slug the diagram lookup expects (no key drift).
    for key, entry in BG.BOSS_DATA.items():
        if entry.has_diagram:
            assert canonical_path(key).endswith(f"{key}.png")


def _main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"ok  {t.__name__}")
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} bossguide-data tests passed")
    sys.exit(failed)


if __name__ == "__main__":
    _main()
