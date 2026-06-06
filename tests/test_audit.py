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
    _tally_casts, audit_combatant, build_roster_audit, check_consumes,
    check_enchants, check_end_activity, check_gems, check_meta, check_rotation,
    parse_report_url,
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

def test_check_meta_active_inactive_missing():
    prof = get_profile("ele_shaman")  # recommends Chaotic Skyfire Diamond (34220)
    CSD = 34220
    blue = {"color": "Blue"}
    red = {"color": "Red"}

    # No meta socket at all → nothing to judge (None)
    assert check_meta({"meta_socket": False}, prof) is None

    # Meta socket but no meta gem → WARN (this is the gap the old code missed)
    miss = check_meta({"meta_socket": True, "meta_id": None, "gems": []}, prof)
    assert miss.verdict == Verdict.WARN and "no meta gem" in miss.summary.lower()

    # Meta socketed with 2 blue gems → active
    active = check_meta({"meta_socket": True, "meta_id": CSD,
                         "gems": [blue, blue, red]}, prof)
    assert active.verdict == Verdict.PASS and "active" in active.summary

    # Meta socketed but 0 blue → INACTIVE (verified requirement) → FAIL
    inactive = check_meta({"meta_socket": True, "meta_id": CSD,
                           "gems": [red, red]}, prof)
    assert inactive.verdict == Verdict.FAIL and "INACTIVE" in inactive.summary

    # Compound gems count: a Purple gem (red+blue) helps satisfy "2 Blue"
    compound = check_meta({"meta_socket": True, "meta_id": CSD,
                           "gems": [{"color": "Purple"}, {"color": "Green"}]}, prof)
    assert compound.verdict == Verdict.PASS  # purple + green = 2 blue


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
    res = check_gems([{"quality": "rare"}], prof, empty_sockets=3)
    assert res.verdict == Verdict.FAIL
    assert "empty socket" in res.summary
    clean = check_gems([{"quality": "rare"}], prof, empty_sockets=0)
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


def test_dps_consumes_flask_covers_elixirs_and_flags_weapon_buff():
    fury = get_profile("fury_warrior")
    # Flask satisfies both elixir slots; food + sharpening stone present → PASS
    full = check_consumes([{"name": "Flask of Relentless Assault"},
                           {"name": "Well Fed"},
                           {"name": "Adamantite Sharpening Stone"}], fury)
    assert full.verdict == Verdict.PASS, full.summary
    # Drop the (required) weapon stone → FAIL, and it's the melee stone, not an oil
    no_stone = check_consumes([{"name": "Flask of Relentless Assault"},
                               {"name": "Well Fed"}], fury)
    assert no_stone.verdict == Verdict.FAIL
    assert "Sharpening Stone" in no_stone.summary


def test_all_healer_specs_have_profiles():
    for s in ("holy_paladin", "holy_priest", "resto_druid", "resto_shaman"):
        p = get_profile(s)
        assert p is not None and p.role == "healer"
        assert p.end_silence_warn_sec > 0           # healers get the OOM check
        assert p.meta_gem == "Insightful Earthstorm Diamond"


def test_healer_consumes_uses_mana_oil_not_wizard():
    rs = get_profile("resto_shaman")
    ok = check_consumes([{"name": "Flask of Mighty Restoration"},
                         {"name": "Golden Fish Sticks"},
                         {"name": "Superior Mana Oil"}], rs)
    assert ok.verdict == Verdict.PASS, ok.summary
    # a DPS wizard oil must NOT satisfy a healer's weapon-buff slot
    no_oil = check_consumes([{"name": "Flask of Mighty Restoration"},
                             {"name": "Golden Fish Sticks"},
                             {"name": "Superior Wizard Oil"}], rs)
    assert no_oil.verdict == Verdict.FAIL
    assert "Mana Oil" in no_oil.summary


def test_check_end_activity_flags_trailing_silence():
    rs = get_profile("resto_shaman")
    window = (0, 300_000)  # 300s fight
    # cast only up to 250s → 50s of silence → WARN (OOM indicator)
    oom = check_end_activity(list(range(0, 250_001, 1000)), window, rs)
    assert oom.verdict == Verdict.WARN and "final 50s" in oom.summary
    # cast through ~298s → tiny trailing lull → PASS
    fine = check_end_activity(list(range(0, 298_001, 1000)), window, rs)
    assert fine.verdict == Verdict.PASS
    # DPS opt out entirely → None (never penalise throughput)
    assert check_end_activity([1, 2, 3], window, get_profile("fire_mage")) is None


def test_all_tank_specs_have_profiles():
    for s in ("prot_warrior", "prot_paladin", "feral_bear_druid"):
        p = get_profile(s)
        assert p is not None and p.role == "tank"
        assert p.meta_gem == "Powerful Earthstorm Diamond"
        assert p.end_silence_warn_sec == 0      # tanks don't get the OOM check
    # shield tanks enchant the Off Hand (shield); bears carry no weapon enchant
    assert "Off Hand" in get_profile("prot_warrior").enchantable_slots
    assert "Main Hand" not in get_profile("feral_bear_druid").enchantable_slots


def test_tally_casts_counts_potions_and_times():
    abilities = [{"gameID": 1, "name": "Shadow Bolt"},
                 {"gameID": 2, "name": "Super Mana Potion"},
                 {"gameID": 3, "name": "Haste Potion"}]
    casts = [
        {"type": "cast", "sourceID": 7, "abilityGameID": 1, "timestamp": 1000},
        {"type": "cast", "sourceID": 7, "abilityGameID": 2, "timestamp": 2000},  # potion
        {"type": "begincast", "sourceID": 7, "abilityGameID": 1, "timestamp": 2500},  # ignored
        {"type": "cast", "sourceID": 7, "abilityGameID": 3, "timestamp": 9000},  # potion
        {"type": "cast", "sourceID": 9, "abilityGameID": 1, "timestamp": 1500},
    ]
    tally = _tally_casts(casts, abilities)
    assert tally[7]["potions"] == 2
    assert tally[7]["cast_times"] == [1000, 2000, 9000]
    assert tally[9]["potions"] == 0


def test_check_consumes_potion_count_drives_verdict():
    rs = get_profile("combat_rogue")
    base = [{"name": "Flask of Relentless Assault"}, {"name": "Grilled Mudfish"},
            {"name": "Adamantite Sharpening Stone"}]
    used = check_consumes(base, rs, potion_count=2)
    assert "Potions: ✅ 2 used" in used.summary and used.verdict == Verdict.PASS
    none_used = check_consumes(base, rs, potion_count=0)
    assert "Potions: ❌" in none_used.summary and none_used.verdict == Verdict.WARN


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


def test_offline_roster_audit_against_fixtures():
    """End-to-end through the fixture transport + real item DB — no creds, no network."""
    import json as _json
    import os as _os
    from tools.fixtures import FIXTURE_WCL_DIR, ensure_item_db

    code = "SYNTHLOG00000001"
    specs_path = _os.path.join(FIXTURE_WCL_DIR, f"{code}.specs.json")
    if not _os.path.exists(specs_path):
        return  # synthetic fixtures not generated in this checkout — skip
    specs = _json.load(open(specs_path, encoding="utf-8"))

    _os.environ["WCL_FIXTURE_DIR"] = FIXTURE_WCL_DIR
    ensure_item_db()  # point config.ITEM_DB_PATH at the committed item-DB fixture
    try:
        roster = build_roster_audit(
            f"https://classic.warcraftlogs.com/reports/{code}",
            lambda n, c="": specs.get(n.lower()),
        )
    finally:
        _os.environ.pop("WCL_FIXTURE_DIR", None)

    assert len(roster.reports) == 8
    out = roster.render()
    assert "missing major: Legs" in out          # enchant severity (major)
    assert "empty socket" in out                  # empty sockets vs the real item DB
    assert "below rare quality" in out            # green gems
    assert "Weapon Oil: ❌" in out                 # missing consume
    assert "Potions: ✅" in out and "Potions: ❌" in out   # potion counting from casts
    assert "no casts for the final" in out        # healer end-of-fight silence
    assert "INACTIVE" in out                       # meta activation (requirement unmet)
    assert "no meta gem socketed" in out           # missing meta gem (the critical gap)


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
