"""
core/simexport.py — Build a WowSims-compatible JSON export from a GearSnapshot.

WowSims import format: https://wowsims.github.io/tbc/
Each class sim accepts a JSON blob matching the proto schema. We produce a
fully-populated player block with gear (item IDs, enchants, gems from WCL),
spec-appropriate rotation and consume defaults, and EP weights from the
optimizer. Talent string is left blank for the user to fill in wowsims.
"""

from __future__ import annotations

from db.server_config import get_guild_phase

# ---------------------------------------------------------------------------
# Slot ordering: wowsims items array is always 17 entries, index = slot
# ---------------------------------------------------------------------------

_WOWSIMS_SLOT_ORDER = [
    "Head",       # 0
    "Neck",       # 1
    "Shoulder",   # 2
    "Back",       # 3
    "Chest",      # 4
    "Wrist",      # 5
    "Hands",      # 6
    "Waist",      # 7
    "Legs",       # 8
    "Feet",       # 9
    "Ring",       # 10  (first ring)
    "Ring",       # 11  (second ring)
    "Trinket",    # 12  (first trinket)
    "Trinket",    # 13  (second trinket)
    "Main Hand",  # 14
    "Off Hand",   # 15
    "Ranged",     # 16  (totem / wand / relic)
]

_RANGED_ALIASES = {"Ranged", "Totem", "Wand", "Relic", "Idol", "Libram"}

# ---------------------------------------------------------------------------
# Race mapping: WCL numeric race ID → wowsims Race string
# ---------------------------------------------------------------------------

_WCL_RACE = {
    1:  "RaceHuman",
    2:  "RaceOrc",
    3:  "RaceDwarf",
    4:  "RaceNightElf",
    5:  "RaceUndead",
    6:  "RaceTauren",
    7:  "RaceGnome",
    8:  "RaceTroll",
    10: "RaceBloodElf",
    11: "RaceDraenei",
}

# ---------------------------------------------------------------------------
# Spec → (wowsims class string, wowsims spec object key)
# ---------------------------------------------------------------------------

_SPEC_CLASS = {
    "elemental":       ("ClassShaman",   "elementalShaman"),
    "restoration":     ("ClassShaman",   "restoShaman"),
    "enhancement":     ("ClassShaman",   "enhancementShaman"),
    "destruction":     ("ClassWarlock",  "destructionWarlock"),
    "affliction":      ("ClassWarlock",  "afflictionWarlock"),
    "demonology":      ("ClassWarlock",  "demonologyWarlock"),
    "fire":            ("ClassMage",     "fireMage"),
    "frost":           ("ClassMage",     "frostMage"),
    "arcane":          ("ClassMage",     "arcaneMage"),
    "shadow":          ("ClassPriest",   "shadowPriest"),
    "holy":            ("ClassPriest",   "holyPriest"),
    "discipline":      ("ClassPriest",   "holyPriest"),
    "balance":         ("ClassDruid",    "balanceDruid"),
    "feral":           ("ClassDruid",    "feralDruid"),
    "beastmastery":    ("ClassHunter",   "beastMasteryHunter"),
    "marksmanship":    ("ClassHunter",   "marksmanshipHunter"),
    "survival":        ("ClassHunter",   "survivalHunter"),
    "retribution":     ("ClassPaladin",  "retributionPaladin"),
    "combat":          ("ClassRogue",    "combatRogue"),
    "assassination":   ("ClassRogue",    "assassinationRogue"),
    "subtlety":        ("ClassRogue",    "subtletyRogue"),
    "arms":            ("ClassWarrior",  "armsWarrior"),
    "fury":            ("ClassWarrior",  "furyWarrior"),
    "protection":      ("ClassWarrior",  "protectionWarrior"),
}

# ---------------------------------------------------------------------------
# Spec-specific rotation/options defaults
# ---------------------------------------------------------------------------

_SPEC_ROTATION = {
    "elementalShaman": {
        "rotation": {
            "totems": {
                "earth": "TremorTotem",
                "air":   "WrathOfAirTotem",
                "fire":  "TotemOfWrath",
                "water": "ManaSpringTotem",
            },
            "type": "Adaptive",
        },
        "talents": {},
        "options": {"waterShield": True, "bloodlust": True},
    },
    "restoShaman": {
        "rotation": {
            "totems": {
                "earth": "TremorTotem",
                "air":   "WrathOfAirTotem",
                "fire":  "TotemOfWrath",
                "water": "ManaSpringTotem",
            },
        },
        "talents": {},
        "options": {"waterShield": True, "bloodlust": True},
    },
    "enhancementShaman": {
        "rotation": {},
        "talents": {},
        "options": {"waterShield": False, "bloodlust": True},
    },
    "destructionWarlock": {
        "rotation": {"primarySpell": "Shadowbolt"},
        "talents": {},
        "options": {},
    },
    "afflictionWarlock": {
        "rotation": {},
        "talents": {},
        "options": {},
    },
    "demonologyWarlock": {
        "rotation": {},
        "talents": {},
        "options": {},
    },
    "shadowPriest": {
        "rotation": {},
        "talents": {},
        "options": {},
    },
    "fireMage": {
        "rotation": {},
        "talents": {},
        "options": {},
    },
    "frostMage": {
        "rotation": {},
        "talents": {},
        "options": {},
    },
    "arcaneMage": {
        "rotation": {},
        "talents": {},
        "options": {},
    },
    "balanceDruid": {
        "rotation": {},
        "talents": {},
        "options": {},
    },
    "beastMasteryHunter": {
        "rotation": {},
        "talents": {},
        "options": {},
    },
    "marksmanshipHunter": {
        "rotation": {},
        "talents": {},
        "options": {},
    },
    "survivalHunter": {
        "rotation": {},
        "talents": {},
        "options": {},
    },
    "retributionPaladin": {
        "rotation": {},
        "talents": {},
        "options": {},
    },
    "combatRogue": {
        "rotation": {},
        "talents": {},
        "options": {},
    },
    "assassinationRogue": {
        "rotation": {},
        "talents": {},
        "options": {},
    },
    "armsWarrior": {
        "rotation": {},
        "talents": {},
        "options": {},
    },
    "furyWarrior": {
        "rotation": {},
        "talents": {},
        "options": {},
    },
}

_DEFAULT_ROTATION = {"rotation": {}, "talents": {}, "options": {}}

# ---------------------------------------------------------------------------
# Spec-specific consumes
# ---------------------------------------------------------------------------

_SPEC_CONSUMES = {
    "elementalShaman": {
        "flask": "FlaskOfBlindingLight",
        "mainHandImbue": "WeaponImbueBrilliantWizardOil",
        "food": "FoodBlackenedBasilisk",
        "defaultPotion": "SuperManaPotion",
        "drums": "DrumsOfBattle",
    },
    "restoShaman": {
        "flask": "FlaskOfBlindingLight",
        "mainHandImbue": "WeaponImbueRighteousWeaponCoating",
        "food": "FoodBlackenedBasilisk",
        "defaultPotion": "SuperManaPotion",
        "drums": "DrumsOfBattle",
    },
    "enhancementShaman": {
        "flask": "FlaskOfRelentlessAssault",
        "mainHandImbue": "WeaponImbueWintersfall",
        "offHandImbue": "WeaponImbueWintersfall",
        "food": "FoodGrilledMudfish",
        "defaultPotion": "HastePotion",
        "drums": "DrumsOfBattle",
    },
    "destructionWarlock": {
        "flask": "FlaskOfPureDeath",
        "mainHandImbue": "WeaponImbueBrilliantWizardOil",
        "food": "FoodBlackenedBasilisk",
        "defaultPotion": "DestructionPotion",
        "drums": "DrumsOfBattle",
    },
    "afflictionWarlock": {
        "flask": "FlaskOfPureDeath",
        "mainHandImbue": "WeaponImbueBrilliantWizardOil",
        "food": "FoodBlackenedBasilisk",
        "defaultPotion": "SuperManaPotion",
        "drums": "DrumsOfBattle",
    },
    "demonologyWarlock": {
        "flask": "FlaskOfPureDeath",
        "mainHandImbue": "WeaponImbueBrilliantWizardOil",
        "food": "FoodBlackenedBasilisk",
        "defaultPotion": "SuperManaPotion",
        "drums": "DrumsOfBattle",
    },
    "shadowPriest": {
        "flask": "FlaskOfPureDeath",
        "mainHandImbue": "WeaponImbueBrilliantWizardOil",
        "food": "FoodBlackenedBasilisk",
        "defaultPotion": "SuperManaPotion",
        "drums": "DrumsOfBattle",
    },
    "fireMage": {
        "flask": "FlaskOfPureDeath",
        "mainHandImbue": "WeaponImbueBrilliantWizardOil",
        "food": "FoodBlackenedBasilisk",
        "defaultPotion": "DestructionPotion",
        "drums": "DrumsOfBattle",
    },
    "frostMage": {
        "flask": "FlaskOfBlindingLight",
        "mainHandImbue": "WeaponImbueBrilliantWizardOil",
        "food": "FoodBlackenedBasilisk",
        "defaultPotion": "SuperManaPotion",
        "drums": "DrumsOfBattle",
    },
    "arcaneMage": {
        "flask": "FlaskOfBlindingLight",
        "mainHandImbue": "WeaponImbueBrilliantWizardOil",
        "food": "FoodBlackenedBasilisk",
        "defaultPotion": "SuperManaPotion",
        "drums": "DrumsOfBattle",
    },
    "balanceDruid": {
        "flask": "FlaskOfBlindingLight",
        "mainHandImbue": "WeaponImbueBrilliantWizardOil",
        "food": "FoodBlackenedBasilisk",
        "defaultPotion": "SuperManaPotion",
        "drums": "DrumsOfBattle",
    },
    "beastMasteryHunter": {
        "flask": "FlaskOfRelentlessAssault",
        "food": "FoodGrilledMudfish",
        "defaultPotion": "HastePotion",
        "drums": "DrumsOfBattle",
    },
    "marksmanshipHunter": {
        "flask": "FlaskOfRelentlessAssault",
        "food": "FoodGrilledMudfish",
        "defaultPotion": "HastePotion",
        "drums": "DrumsOfBattle",
    },
    "survivalHunter": {
        "flask": "FlaskOfRelentlessAssault",
        "food": "FoodGrilledMudfish",
        "defaultPotion": "HastePotion",
        "drums": "DrumsOfBattle",
    },
    "retributionPaladin": {
        "flask": "FlaskOfRelentlessAssault",
        "mainHandImbue": "WeaponImbueRighteousWeaponCoating",
        "food": "FoodRoastedClefthoof",
        "defaultPotion": "HastePotion",
        "drums": "DrumsOfBattle",
    },
    "combatRogue": {
        "flask": "FlaskOfRelentlessAssault",
        "mainHandImbue": "WeaponImbueDeadlyPoison",
        "offHandImbue": "WeaponImbueDeadlyPoison",
        "food": "FoodGrilledMudfish",
        "defaultPotion": "HastePotion",
        "drums": "DrumsOfBattle",
    },
    "assassinationRogue": {
        "flask": "FlaskOfRelentlessAssault",
        "mainHandImbue": "WeaponImbueDeadlyPoison",
        "offHandImbue": "WeaponImbueDeadlyPoison",
        "food": "FoodGrilledMudfish",
        "defaultPotion": "HastePotion",
        "drums": "DrumsOfBattle",
    },
    "furyWarrior": {
        "flask": "FlaskOfRelentlessAssault",
        "mainHandImbue": "WeaponImbueRighteousWeaponCoating",
        "offHandImbue": "WeaponImbueRighteousWeaponCoating",
        "food": "FoodRoastedClefthoof",
        "defaultPotion": "HastePotion",
        "drums": "DrumsOfBattle",
    },
    "armsWarrior": {
        "flask": "FlaskOfRelentlessAssault",
        "mainHandImbue": "WeaponImbueRighteousWeaponCoating",
        "food": "FoodRoastedClefthoof",
        "defaultPotion": "HastePotion",
        "drums": "DrumsOfBattle",
    },
}

_DEFAULT_CONSUMES = {
    "flask": "FlaskOfBlindingLight",
    "food": "FoodBlackenedBasilisk",
    "defaultPotion": "SuperManaPotion",
    "drums": "DrumsOfBattle",
}

# ---------------------------------------------------------------------------
# EP weights → wowsims stat array
# Indices match wowsims TBC proto/common.proto Stat enum
# ---------------------------------------------------------------------------

_STAT_IDX = {
    "Strength":          0,
    "Agility":           1,
    "Stamina":           2,
    "Intellect":         3,
    "Spirit":            4,
    "SpellPower":        5,
    "ArcaneSpellPower":  6,
    "FireSpellPower":    7,
    "FrostSpellPower":   8,
    "HolySpellPower":    9,
    "ShadowSpellPower":  10,
    "NatureSpellPower":  11,
    "MP5":               12,
    "SpellHit":          13,
    # 14 = SpellPenetration
    "SpellCrit":         15,
    "SpellHaste":        16,
    "AttackPower":       17,
    "RangedAttackPower": 18,
    "Armor":             19,
    "Defense":           20,
    "Dodge":             21,
    "Parry":             22,
    "Block":             23,
    "BlockValue":        24,
    "MeleeHit":          25,
    "MeleeCrit":         26,
    "MeleeHaste":        27,
    "ArmorPenetration":  28,
    "Expertise":         29,
    "HealingPower":      37,
    "Resilience":        36,
}

_STAT_ARRAY_LEN = 42

_SPEC_EP = {
    "elemental": {
        "SpellHit": 2.00, "SpellPower": 1.00, "NatureSpellPower": 1.00,
        "SpellHaste": 1.30, "SpellCrit": 0.80,
        "Intellect": 0.35, "MP5": 0.15, "Spirit": 0.05,
    },
    "destruction": {
        "SpellHit": 2.00, "SpellPower": 1.00, "FireSpellPower": 1.00,
        "SpellHaste": 1.30, "SpellCrit": 0.80,
        "Intellect": 0.25, "MP5": 0.10,
    },
    "affliction": {
        "SpellHit": 2.00, "SpellPower": 1.00, "ShadowSpellPower": 1.00,
        "SpellHaste": 1.20, "SpellCrit": 0.60,
        "Intellect": 0.30, "MP5": 0.15, "Spirit": 0.20,
    },
    "shadow": {
        "SpellHit": 2.00, "SpellPower": 1.00, "ShadowSpellPower": 1.00,
        "SpellHaste": 1.20, "SpellCrit": 0.70,
        "Intellect": 0.25, "MP5": 0.10, "Spirit": 0.40,
    },
    "balance": {
        "SpellHit": 2.00, "SpellPower": 1.00, "NatureSpellPower": 1.00,
        "SpellHaste": 1.20, "SpellCrit": 0.80,
        "Intellect": 0.30, "MP5": 0.15,
    },
    "fire": {
        "SpellHit": 2.00, "SpellPower": 1.00, "FireSpellPower": 1.00,
        "SpellHaste": 1.30, "SpellCrit": 0.85,
        "Intellect": 0.25, "MP5": 0.10,
    },
    "frost": {
        "SpellHit": 2.00, "SpellPower": 1.00, "FrostSpellPower": 1.00,
        "SpellHaste": 1.20, "SpellCrit": 0.80,
        "Intellect": 0.25, "MP5": 0.10,
    },
    "arcane": {
        "SpellHit": 2.00, "SpellPower": 1.00,
        "SpellHaste": 1.30, "SpellCrit": 0.80,
        "Intellect": 0.50, "MP5": 0.20,
    },
}


def _ep_array(spec: str) -> list[float]:
    weights = _SPEC_EP.get(spec.lower(), {})
    arr = [0.0] * _STAT_ARRAY_LEN
    for stat, w in weights.items():
        idx = _STAT_IDX.get(stat)
        if idx is not None:
            arr[idx] = round(w, 2)
    return arr


# ---------------------------------------------------------------------------
# Equipment builder
# ---------------------------------------------------------------------------

def _build_items(gear: list) -> list[dict]:
    """Map snapshot gear list to a 17-element wowsims items array (index = slot)."""
    by_slot: dict[str, list] = {}
    for item in gear:
        slot = item["slot"]
        if slot in _RANGED_ALIASES:
            slot = "Ranged"
        by_slot.setdefault(slot, []).append(item)

    # Two-hander fills Main Hand; Off Hand becomes empty
    two_hand = by_slot.pop("Two-Hand", [])
    if two_hand:
        by_slot["Main Hand"] = two_hand
        by_slot.pop("Off Hand", None)

    ring_idx = trinket_idx = 0
    items = []

    for slot_name in _WOWSIMS_SLOT_ORDER:
        slot_items = by_slot.get(slot_name, [])

        if slot_name == "Ring":
            item = slot_items[ring_idx] if ring_idx < len(slot_items) else None
            ring_idx += 1
        elif slot_name == "Trinket":
            item = slot_items[trinket_idx] if trinket_idx < len(slot_items) else None
            trinket_idx += 1
        else:
            item = slot_items[0] if slot_items else None

        if not item:
            items.append({})
            continue

        entry: dict = {"id": item["item_id"]}
        enchant = item.get("enchant", 0) or 0
        gems    = [g for g in item.get("gems", []) if g]
        if enchant:
            entry["enchant"] = enchant
        if gems:
            entry["gems"] = gems
        items.append(entry)

    return items


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_simexport(snapshot, spec: str, guild_id: str,
                    phase_override: int | None = None) -> dict:
    """
    Build a wowsims-compatible settings dict from a GearSnapshot.

    Returns a dict ready for json.dumps(). Talent string is left blank —
    user fills it in wowsims after import.
    """
    phase       = phase_override if phase_override is not None else get_guild_phase(guild_id)
    faction_str = "Alliance" if snapshot.faction == 1 else "Horde"
    race_id     = snapshot.combat_stats.get("race", 0)
    race_str    = _WCL_RACE.get(race_id, "RaceDraenei")

    class_str, spec_key = _SPEC_CLASS.get(spec.lower(), ("ClassShaman", "elementalShaman"))

    has_enchants = any(item.get("enchant") for item in snapshot.gear)
    has_gems     = any(item.get("gems")    for item in snapshot.gear)

    player = {
        "name":      snapshot.character,
        "race":      race_str,
        "class":     class_str,
        "equipment": {"items": _build_items(snapshot.gear)},
        "consumes":  _SPEC_CONSUMES.get(spec_key, _DEFAULT_CONSUMES),
        "bonusStats":    [0] * _STAT_ARRAY_LEN,
        "buffs": {
            "blessingOfKings":    True,
            "blessingOfSalvation": True,
            "blessingOfWisdom":   "TristateEffectImproved",
        },
        "talentsString": "",
        "cooldowns":   {},
        "healingModel": {},
        spec_key: _SPEC_ROTATION.get(spec_key, _DEFAULT_ROTATION),
    }

    return {
        "_brnzybot": {
            "character":   snapshot.character,
            "spec":        spec,
            "phase":       phase,
            "from_cache":  snapshot.from_cache,
            "has_enchants": has_enchants,
            "has_gems":    has_gems,
            "note": (
                "Talent string is blank — paste yours into wowsims after import. "
                "Buffs/consumes are spec defaults; adjust as needed."
                + ("" if has_enchants else " Enchant data unavailable (cached snapshot) — add manually.")
                + ("" if has_gems     else " Gem data unavailable (cached snapshot) — add manually.")
            ),
        },
        "settings": {
            "iterations": 3000,
            "phase":      phase,
            "faction":    faction_str,
        },
        "raidBuffs": {
            "arcaneBrilliance":  True,
            "divineSpirit":      "TristateEffectImproved",
            "giftOfTheWild":     "TristateEffectImproved",
        },
        "debuffs": {
            "judgementOfWisdom": True,
            "misery":            True,
        },
        "partyBuffs": {},
        "player":    player,
        "encounter": {
            "duration":          180,
            "durationVariation": 5,
            "executeProportion": 0.2,
            "targets": [{
                "level":        73,
                "mobType":      "MobTypeDemon",
                "stats":        [0] * _STAT_ARRAY_LEN,
                "minBaseDamage": 10000,
                "swingSpeed":   2,
                "canCrush":     True,
                "parryHaste":   True,
            }],
        },
        "epWeights": _ep_array(spec),
    }
