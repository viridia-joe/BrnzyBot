"""
Tests for the realm-driven phase model (docs/PHASE_READINESS.md s1).

Pins the two-axis design: calendar_phase (user-facing) vs content_phase_max
(optimizer item ceiling), the auto-advance on release dates, the ZA-ceiling fix,
and the phase_override DB migration/accessors.

    python tests/test_phase.py
"""

import os
import sqlite3
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import phase as P
from db import server_config as SC


def test_auto_advances_on_release_dates():
    # Before P1 release -> phase 1 (nothing released yet).
    assert P.resolve_phase("dreamscythe", today=date(2026, 1, 1)).calendar_phase == 1
    # P1 window.
    assert P.resolve_phase("dreamscythe", today=date(2026, 3, 1)).calendar_phase == 1
    # On/after P2 release.
    p2 = P.resolve_phase("dreamscythe", today=date(2026, 5, 14))
    assert p2.calendar_phase == 2 and p2.content_phase_max == 2
    assert p2.source == "auto"


def test_undated_future_phase_holds_previous():
    # P3/P4 have release=null -> they must not become current no matter the date.
    far = P.resolve_phase("dreamscythe", today=date(2027, 1, 1))
    assert far.calendar_phase == 2, "undated phases must not auto-activate"


def test_za_ceiling_fix():
    # The crux: calendar P3 folds in Zul'Aman, whose gear is item content-phase 4.
    p3 = P.resolve_phase("dreamscythe", override=3)
    assert p3.calendar_phase == 3
    assert p3.content_phase_max == 4, "P3 optimizer ceiling must include ZA (content-phase 4)"
    assert "Zul'Aman" in p3.raids
    p4 = P.resolve_phase("dreamscythe", override=4)
    assert p4.content_phase_max == 5


def test_override_is_clamped_and_flagged():
    hi = P.resolve_phase("dreamscythe", override=99)
    assert hi.calendar_phase == P.max_calendar_phase("dreamscythe") == 4
    assert hi.source == "override"
    lo = P.resolve_phase("dreamscythe", override=0)
    assert lo.calendar_phase == 1


def test_unknown_realm_falls_back_to_default():
    info = P.resolve_phase("some-private-server", today=date(2026, 6, 13))
    assert info.ruleset == "anniversary"
    assert info.calendar_phase == 2  # never raises, uses _default


def test_phase_override_migration_and_accessors():
    db = os.path.join(tempfile.mkdtemp(), "b.db")
    SC.init_db(db)
    with sqlite3.connect(db) as c:
        # A guild that deliberately set a non-default legacy phase, and one left default.
        c.execute("INSERT INTO guild_config (guild_id, current_phase) VALUES ('g1', 4)")
        c.execute("INSERT INTO guild_config (guild_id, current_phase) VALUES ('g2', 1)")
    SC.init_db(db)  # re-run migrations -> one-time backfill

    assert SC.get_phase_override("g1", path=db) == 4, "deliberate legacy phase -> override"
    assert SC.get_phase_override("g2", path=db) is None, "default phase -> auto"

    # Clearing to auto must neutralize, and must survive a re-migration.
    SC.set_phase_override("g1", None, path=db)
    assert SC.get_phase_override("g1", path=db) is None
    SC.init_db(db)
    assert SC.get_phase_override("g1", path=db) is None, "backfill must not resurrect a cleared override"

    SC.set_phase_override("g2", 2, path=db)
    assert SC.get_phase_override("g2", path=db) == 2


def test_schedule_file_is_valid():
    sched = P.load_schedule(force=True)
    assert "anniversary" in sched["rulesets"]
    assert sched["realms"]["_default"] == "anniversary"
    # content_phase_max must be monotonic non-decreasing with calendar phase.
    phases = sorted(sched["rulesets"]["anniversary"]["phases"], key=lambda p: p["phase"])
    cmaxes = [p["content_phase_max"] for p in phases]
    assert cmaxes == sorted(cmaxes)


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
    print(f"\n{len(tests) - failed}/{len(tests)} phase tests passed")
    sys.exit(failed)


if __name__ == "__main__":
    _main()
