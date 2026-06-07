"""
Rotation + baseline tests — covers the WCL-derived-baseline / shock-budget /
fuzzy-match code, and (critically) that EVERY committed rotation profile loads.

That load test is the regression guard for the UTF-8 BOM bug: the profiles were
re-saved with a BOM and `load_profile` read plain utf-8, crashing /rotationcheck
for every spec until load_profile switched to utf-8-sig.

    python tests/test_rotation.py    # plain-asserts (runs in CI)
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import rotation_handler as R


def _casts(*pairs, step_ms=2000):
    """(gameID, n) → cast events spaced step_ms apart, so analyze() can derive duration."""
    out, t = [], 0
    for gid, n in pairs:
        for _ in range(n):
            out.append({"type": "cast", "sourceID": 1, "abilityGameID": gid, "timestamp": t})
            t += step_ms
    return out


def test_all_rotation_profiles_load():
    """Regression: every covered spec's profile parses (catches BOM / bad JSON)."""
    specs = R.covered_specs()
    assert specs, "no rotation profiles found"
    for s in specs:
        p = R.load_profile(s)
        assert p and p.get("downrank_watch") is not None, f"{s} failed to load"


def test_load_baseline_fallback(tmp_path=None):
    import json
    orig = R.BASELINES_DIR
    d = tempfile.mkdtemp()
    try:
        R.BASELINES_DIR = d
        os.makedirs(os.path.join(d, "ele_shaman"))
        # fight-specific wins
        with open(os.path.join(d, "ele_shaman", "lady_vashj.json"), "w") as f:
            json.dump({"encounter": "Lady Vashj"}, f)
        with open(os.path.join(d, "ele_shaman", "_generic.json"), "w") as f:
            json.dump({"encounter": "generic"}, f)
        assert R.load_baseline("ele_shaman", "Lady Vashj")["encounter"] == "Lady Vashj"
        # unknown fight → _generic fallback
        assert R.load_baseline("ele_shaman", "Some Trash Pull")["encounter"] == "generic"
        # unknown spec → None
        assert R.load_baseline("fire_mage", "Lady Vashj") is None
    finally:
        R.BASELINES_DIR = orig


def test_analyze_baseline_cpm_tiers():
    abilities = [{"gameID": 101, "name": "Lightning Bolt"}]
    profile = {"core_spells": ["Lightning Bolt"], "downrank_watch": []}
    # 60 casts over ~120s → ~30 cpm
    casts = _casts((101, 60), step_ms=2000)
    low = {"spells": {"Lightning Bolt": {"p25": 40, "p50": 45, "p75": 50, "p95": 55}},
           "sample_size": 50, "encounter": "Gruul"}
    out = R.analyze(casts, abilities, profile, baseline=low)
    joined = "\n".join(out.advisories)
    assert "Cast-rate vs top" in joined and "below p25" in joined

    high = {"spells": {"Lightning Bolt": {"p25": 10, "p50": 15, "p75": 20, "p95": 25}}}
    out2 = R.analyze(casts, abilities, profile, baseline=high)
    assert "top 5%" in "\n".join(out2.advisories)


def test_analyze_shock_budget_ratio():
    abilities = [{"gameID": 1, "name": "Lightning Bolt"}, {"gameID": 2, "name": "Earth Shock"}]
    profile = {
        "core_spells": ["Lightning Bolt"], "downrank_watch": [],
        "off_rotation": {
            "Earth Shock": {"min_casts": 3, "note": "shock as filler",
                            "shared_cooldown_s": 6, "ratio_flag": 0.5},
        },
    }
    # 120s fight; Earth Shock budget = 120/6 = 20; 15 casts = 75% ≥ 50% → ratio note
    casts = _casts((1, 1), step_ms=120000) + _casts((2, 15), step_ms=1000)
    out = R.analyze(casts, abilities, profile)
    es = [o for o in out.off_rotation if "Earth Shock" in o]
    assert es and "cooldown budget" in es[0]


def test_fuzzy_match_character():
    from db import server_config as sc
    db = os.path.join(tempfile.mkdtemp(), "t.db")
    sc.init_db(db)
    sc.add_character("g1", "Shermshaman", "ele_shaman", "gehennas", path=db)
    assert sc.fuzzy_match_character("g1", "shermshamn", path=db) == "Shermshaman"   # typo
    assert sc.fuzzy_match_character("g1", "Zzzqqq", path=db) is None                 # no match


def _main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} rotation tests passed")


if __name__ == "__main__":
    _main()
