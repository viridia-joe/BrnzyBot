"""
Raid-audit tests — validate the deterministic Preparation scoring against the
maintainer's elemental-shaman example (Brnzy vs Shermshaman) before any live WCL
wiring is trusted, plus unit coverage of the pure checks and the normalizer.

Runs with no network, no env, no LLM. Executable two ways:
    python tests/test_audit.py      # plain-asserts harness (used by CI)
    pytest tests/test_audit.py      # also works if pytest is installed
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.audit.checks import Verdict
from core.audit.normalize import normalize_combatant
from core.audit.profiles import ELE_SHAMAN, get_profile
from core.audit.report import (
    audit_combatant, build_roster_audit, check_enchants, check_gems,
    check_rotation, parse_report_url,
)

# Enchantable slot → positional index in the WCL CombatantInfo gear array.
_SLOT_INDEX = {
    "Head": 0, "Neck": 1, "Shoulder": 2, "Chest": 4, "Waist": 5, "Legs": 6,
    "Feet": 7, "Wrist": 8, "Hands": 9, "Back": 14, "Main Hand": 15,
}
_META = 34220  # Chaotic Skyfire Diamond


def _gear_entry(item_id=1000, ilvl=120, enchant=None, gems=None):
    e = {"id": item_id, "itemLevel": ilvl, "quality": 4}
    if enchant is not None:
        e["permanentEnchant"] = enchant
        e["permanentEnchantName"] = f"Enchant {enchant}"
    if gems is not None:
        e["gems"] = gems
    return e


def _combatant(*, enchanted_slots, gems, auras):
    """Build a WCL-shaped CombatantInfo record from a set of enchanted slots."""
    gear = [{"id": 0} for _ in range(19)]  # all slots empty by default
    for slot, idx in _SLOT_INDEX.items():
        gear[idx] = _gear_entry(item_id=1000 + idx,
                                 enchant=111 if slot in enchanted_slots else None)
    # park the gems in the head slot's sockets (placement is irrelevant to scoring)
    gear[0]["gems"] = gems
    return {"sourceID": 1, "gear": gear, "auras": auras}


# --- fixtures mirroring the example doc -------------------------------------

BRNZY = _combatant(
    enchanted_slots=set(_SLOT_INDEX) - {"Chest", "Feet"},      # 7/9
    gems=[{"id": _META, "itemLevel": 70},                       # meta, rare
          {"id": 40001, "itemLevel": 70},
          {"id": 40002, "itemLevel": 70}],                      # all rare
    auras=[{"name": "Flask of Blinding Light"},
           {"name": "Well Fed"}],                               # NO weapon oil
)

SHERM = _combatant(
    enchanted_slots={"Head", "Shoulder", "Chest", "Main Hand"},  # 4/9
    gems=[{"id": 50001, "itemLevel": 60},
          {"id": 50002, "itemLevel": 60},
          {"id": 50003, "itemLevel": 60}],                       # all green, no meta
    auras=[{"name": "Well Fed"}],                                # no flask, no oil
)


def _verdict(report, key):
    for section in report.sections:
        for c in section.checks:
            if c.key == key:
                return c.verdict
    raise AssertionError(f"check {key!r} not found")


# --- the example, reproduced end-to-end -------------------------------------

def test_brnzy_matches_doc():
    r = audit_combatant("Brnzy", "ele_shaman", ELE_SHAMAN, normalize_combatant(BRNZY))
    assert _verdict(r, "enchants") == Verdict.WARN     # 7/9 (missing 2) → warn
    assert _verdict(r, "gems") == Verdict.PASS         # all rare
    assert _verdict(r, "consumes") == Verdict.FAIL     # missing weapon oil


def test_shermshaman_matches_doc():
    r = audit_combatant("Shermshaman", "ele_shaman", ELE_SHAMAN, normalize_combatant(SHERM))
    assert _verdict(r, "enchants") == Verdict.FAIL     # 4/9
    assert _verdict(r, "gems") == Verdict.FAIL         # 3 green gems
    assert _verdict(r, "consumes") == Verdict.FAIL     # no flask/elixirs/oil


# --- pure-check unit coverage -----------------------------------------------

def test_check_gems_flags_missing_meta():
    # all rare but no meta → only the meta warning fires (this is the path the
    # live roster can't assert, so we cover it directly).
    res = check_gems([{"quality": "rare"}, {"quality": "rare"}], ELE_SHAMAN,
                     meta_present=False)
    assert res.verdict == Verdict.WARN
    assert "meta" in res.summary.lower()


def test_enchant_severity_major_vs_minor():
    prof = get_profile("destro_warlock")
    slots = list(prof.enchantable_slots)

    def gear(missing):
        return [{"slot": s, "item_id": 1, "enchant_id": (0 if s in missing else 9)}
                for s in slots]

    # Missing the weapon (a major slot) is a real loss → FAIL
    major = check_enchants(gear({"Main Hand"}), prof)
    assert major.verdict == Verdict.FAIL
    assert "Main Hand" in major.summary
    # Missing only boots (a minor slot) is A → A+ → WARN
    minor = check_enchants(gear({"Feet"}), prof)
    assert minor.verdict == Verdict.WARN
    # Fully enchanted → PASS
    assert check_enchants(gear(set()), prof).verdict == Verdict.PASS


def test_check_gems_flags_empty_sockets():
    prof = get_profile("destro_warlock")
    res = check_gems([{"quality": "rare"}], prof, meta_present=True, empty_sockets=3)
    assert res.verdict == Verdict.FAIL
    assert "empty socket" in res.summary
    clean = check_gems([{"quality": "rare"}], prof, meta_present=True, empty_sockets=0)
    assert clean.verdict == Verdict.PASS


def test_all_dps_specs_have_audit_profiles():
    dps = [
        "affliction_warlock", "destro_warlock", "fire_destro_warlock", "arcane_mage",
        "fire_mage", "frost_mage", "shadow_priest", "balance_druid", "ele_shaman",
        "arms_warrior", "fury_warrior", "ret_paladin", "combat_rogue",
        "assassination_rogue", "enh_shaman", "feral_cat_druid",
        "bm_hunter", "mm_hunter", "survival_hunter",
    ]
    assert all(get_profile(s) is not None for s in dps)
    # dual-wielders carry an Off Hand enchant slot; feral (forms) carries none on weapons
    assert "Off Hand" in get_profile("fury_warrior").enchantable_slots
    assert "Main Hand" not in get_profile("feral_cat_druid").enchantable_slots


def test_check_rotation_flags_earth_shock_filler():
    counts = {"Lightning Bolt": 80, "Chain Lightning": 20, "Earth Shock": 16}
    res = check_rotation(counts, ELE_SHAMAN)
    assert res.verdict == Verdict.FAIL
    assert "Earth Shock" in res.summary


def test_check_rotation_clean_is_pass():
    res = check_rotation({"Lightning Bolt": 90, "Chain Lightning": 30}, ELE_SHAMAN)
    assert res.verdict == Verdict.PASS


# --- normalizer -------------------------------------------------------------

def test_normalize_drops_empty_and_cosmetic_slots():
    rec = {
        "sourceID": 7,
        "gear": [
            _gear_entry(item_id=10, ilvl=120, enchant=5),   # 0 Head
            {"id": 0},                                       # 1 Neck (empty)
            _gear_entry(item_id=11, ilvl=100),               # 2 Shoulder, no enchant
        ] + [{"id": 0}] * 16,
        "auras": [{"name": "Flask of Supreme Power"}, "Blackened Basilisk"],
    }
    norm = normalize_combatant(rec)
    slots = [g["slot"] for g in norm["gear"]]
    assert slots == ["Head", "Shoulder"]                    # empty + cosmetics dropped
    assert norm["avg_item_level"] == 110.0                  # (120 + 100) / 2
    assert {a["name"] for a in norm["auras"]} == {"Flask of Supreme Power",
                                                  "Blackened Basilisk"}


def test_normalize_gem_quality_by_itemlevel():
    rec = {"sourceID": 1, "gear": [{"id": 1, "itemLevel": 120, "gems": [
        {"id": 1, "itemLevel": 110},   # epic
        {"id": 2, "itemLevel": 70},    # rare
        {"id": 3, "itemLevel": 60},    # green
    ]}] + [{"id": 0}] * 18}
    quals = [g["quality"] for g in normalize_combatant(rec)["gems"]]
    assert quals == ["epic", "rare", "uncommon"]


def test_parse_report_url():
    code, fight = parse_report_url("https://classic.warcraftlogs.com/reports/aBcD1234EfGh5678?fight=12")
    assert code == "aBcD1234EfGh5678"
    assert fight == "12"
    assert parse_report_url("not a url") == (None, None)


def test_roster_surfaces_unprofiled_players():
    # No network: a bad URL short-circuits before any WCL call, exercising the
    # roster result shape deterministically.
    roster = build_roster_audit("garbage", lambda n, c: None)
    assert roster.reports == []
    assert roster.warnings  # parse failure recorded


def test_get_profile_unknown_is_none():
    assert get_profile("totally_made_up_spec") is None
    assert get_profile("ele_shaman") is ELE_SHAMAN


# --- plain-asserts harness for CI (no pytest needed) ------------------------

def _main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} audit tests passed")


if __name__ == "__main__":
    _main()
