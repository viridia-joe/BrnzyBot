"""
Offline gearcheck test — proves /gearcheck's gear fetch replays through the
UNIFIED WCL client (core.wcl_client) with no creds and no network, using the
committed item-DB fixture + the synthetic WCL fixtures.

This is the parity check for the gear_cache → wcl_client unification: gear_cache
no longer has its own OAuth/GraphQL transport.

    python tests/test_gear_offline.py     # plain-asserts (runs in CI)
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.fixtures import FIXTURE_WCL_DIR, ensure_item_db, use_wcl_fixtures


def test_get_gear_replays_through_unified_client():
    if not os.path.exists(os.path.join(FIXTURE_WCL_DIR, "character.zappy.json")):
        return  # synthetic fixtures not generated in this checkout — skip
    use_wcl_fixtures()
    db = ensure_item_db()
    assert db, "item DB fixture missing"

    from core.gear_cache import get_gear
    conn = sqlite3.connect(db)
    try:
        snap = get_gear("Zappy", "gehennas", "ele_shaman", item_db_conn=conn)
    finally:
        conn.close()
        os.environ.pop("WCL_FIXTURE_DIR", None)

    assert snap is not None, "get_gear returned None under fixtures"
    assert snap.report_code == "SYNTHLOG00000001"
    assert snap.from_cache is False            # came from the (replayed) WCL path
    assert len(snap.gear) > 0                  # gear resolved against the item DB
    # real socketed items from the fixture resolve to real names (not 'Unknown')
    names = {g["name"] for g in snap.gear}
    assert any("Soulcloth" in n for n in names), names


def _main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} gear-offline tests passed")


if __name__ == "__main__":
    _main()
