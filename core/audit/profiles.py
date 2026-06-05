"""
Raid audit — spec profiles (the "ideal behaviors" rubric).

A ``SpecProfile`` encodes, per spec, what "good" looks like so the audit checks
have a ground truth to compare a log against. These are the *written assumptions*
the maintainer wants to validate against real parses — keep them sourced and
revisable. Start with elemental shaman (the worked example) and add specs over
time. Spec keys match core/classifier.py:VALID_SPECS.

Sources for the seeded ELE_SHAMAN values (TBC Classic, P1–P2):
  - Icy Veins / Wowhead / Warcraft Tavern elemental shaman guides
  - Maintainer scorecard in docs/RAID_AUDIT.md
Numbers are intentionally easy to edit as the meta shifts between phases.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ConsumeRule:
    """An expected consumable slot and the items/auras that satisfy it."""
    slot: str            # "food" | "flask" | "battle_elixir" | "guardian_elixir" | "weapon_oil" | "potion"
    label: str
    accepted: tuple[str, ...]   # acceptable buff/aura or item names (lower-cased match)
    required: bool = True
    note: str = ""

    # A flask satisfies both elixir slots; encode that where relevant in the check.


@dataclass(frozen=True)
class SpecProfile:
    spec: str                  # canonical key, e.g. "ele_shaman"
    display: str               # "Elemental Shaman"
    role: str                  # "caster_dps" | "melee_dps" | "tank" | "healer"

    # ── Baseline ──────────────────────────────────────────────────────────
    standard_build_note: str = ""      # what the cookie-cutter spec looks like

    # ── Execution ─────────────────────────────────────────────────────────
    # Spells that *should* dominate the cast breakdown (rotational core).
    core_spells: tuple[str, ...] = ()
    filler_spell: str = ""
    # Spells whose presence in the rotation is a red flag → why.
    discouraged_spells: dict = field(default_factory=dict)   # name -> reason
    # Spells that are fine/expected situationally (don't penalize).
    situational_spells: tuple[str, ...] = ()
    # Activity (active time) % below this is flagged.
    min_activity_pct: float = 90.0

    # ── Preparation ───────────────────────────────────────────────────────
    # Spell-hit % expected *from gear* after talents/totems (ele = ~4%).
    gear_hit_cap_pct: float = 0.0
    hit_cap_note: str = ""
    enchantable_slots: tuple[str, ...] = ()      # slots that should carry an enchant
    min_gem_quality: str = "rare"                # "rare" (blue) or better; flag "uncommon" (green)
    meta_gem: str = ""
    consumes: tuple[ConsumeRule, ...] = ()


# ---------------------------------------------------------------------------
# Elemental Shaman — the worked example
# ---------------------------------------------------------------------------

ELE_SHAMAN = SpecProfile(
    spec="ele_shaman",
    display="Elemental Shaman",
    role="caster_dps",
    standard_build_note=(
        "Standard build runs deep Elemental for Elemental Mastery, Lightning "
        "Overload, Elemental Precision and Totem of Wrath. Flag large deviations."
    ),
    core_spells=("Chain Lightning", "Lightning Bolt"),
    filler_spell="Lightning Bolt",
    discouraged_spells={
        "Earth Shock": (
            "Earth Shock has a much lower spell coefficient than Lightning Bolt and "
            "is very mana-inefficient — using it as a rotational filler is a DPS loss. "
            "It's an interrupt / on-the-move tool, not a nuke."
        ),
        "Frost Shock": (
            "Frost Shock is a PvP/utility shock; not part of a PvE DPS rotation."
        ),
    },
    situational_spells=("Flame Shock", "Earth Shock"),  # ok for movement/interrupt
    min_activity_pct=90.0,
    gear_hit_cap_pct=4.0,
    hit_cap_note=(
        "Elemental needs only ~4% spell hit from gear: Elemental Precision (3%), "
        "Nature's Guidance (3%) and Totem of Wrath (3%) supply ~9–12% innate "
        "(varies with raid totem coverage). Over the gear cap = wasted itemization."
    ),
    enchantable_slots=(
        "Head", "Shoulder", "Back", "Chest", "Wrist", "Hands", "Legs", "Feet", "Main Hand",
    ),
    min_gem_quality="rare",
    meta_gem="Chaotic Skyfire Diamond",
    consumes=(
        ConsumeRule(
            slot="food", label="Food",
            accepted=("Blackened Basilisk", "Poached Bluefish", "Crunchy Serpent",
                      "Well Fed"),
            note="+spell damage food (Blackened Basilisk preferred).",
        ),
        ConsumeRule(
            slot="flask", label="Flask",
            accepted=("Flask of Blinding Light", "Flask of Supreme Power",
                      "Flask of Pure Death"),
            required=False,
            note="A flask satisfies both elixir slots and survives death.",
        ),
        ConsumeRule(
            slot="battle_elixir", label="Battle Elixir",
            accepted=("Adept's Elixir", "Elixir of Major Firepower"),
            required=False,
            note="Use double-elixirs OR a flask, not both.",
        ),
        ConsumeRule(
            slot="guardian_elixir", label="Guardian Elixir",
            accepted=("Elixir of Draenic Wisdom", "Elixir of Major Mageblood"),
            required=False,
        ),
        ConsumeRule(
            slot="weapon_oil", label="Weapon Oil",
            accepted=("Brilliant Wizard Oil", "Superior Wizard Oil"),
            note="Frequently the most-missed buff (see Brnzy: 'Weapon Buffs: No?').",
        ),
        ConsumeRule(
            slot="potion", label="Mana/Damage Potions",
            accepted=("Super Mana Potion", "Destruction Potion", "Insane Strength Potion"),
            note="Track count used per fight; pre-pot + one per fight is the target.",
        ),
    ),
)


# Registry — extend as profiles are authored.
# ---------------------------------------------------------------------------
# Role-based templates — Preparation data (enchant slots, meta gem, consumes)
# is largely shared by role, so the rest of the DPS specs are built from these
# rather than hand-authored field-by-field. Sourced from Icy Veins / Wowhead /
# WoWTBC consumable & enchant guides (TBC Classic P1–P2). Execution fields are
# left default: audit_combatant scores Preparation only today.
# ---------------------------------------------------------------------------

CASTER_META = "Chaotic Skyfire Diamond"
PHYS_META   = "Relentless Earthstorm Diamond"

# Enchant-bearing slots by weapon layout (labels match normalize.GEAR_SLOTS).
_ARMOR_SLOTS   = ("Head", "Shoulder", "Back", "Chest", "Wrist", "Hands", "Legs", "Feet")
CASTER_SLOTS   = _ARMOR_SLOTS + ("Main Hand",)
MELEE_2H_SLOTS = _ARMOR_SLOTS + ("Main Hand",)            # 2H weapon occupies Main Hand
MELEE_DW_SLOTS = _ARMOR_SLOTS + ("Main Hand", "Off Hand")
FERAL_SLOTS    = _ARMOR_SLOTS                              # weapon enchants don't work in forms
HUNTER_SLOTS   = _ARMOR_SLOTS + ("Relic",)                # Relic index = ranged weapon (scope)

CASTER_CONSUMES = (
    ConsumeRule("food", "Food", ("Blackened Basilisk", "Well Fed"), note="+spell damage food"),
    ConsumeRule("flask", "Flask",
                ("Flask of Supreme Power", "Flask of Pure Death", "Flask of Blinding Light"),
                required=False, note="A flask satisfies both elixir slots."),
    ConsumeRule("battle_elixir", "Battle Elixir",
                ("Adept's Elixir", "Major Firepower", "Major Shadow Power"), required=False),
    ConsumeRule("guardian_elixir", "Guardian Elixir",
                ("Draenic Wisdom", "Major Mageblood"), required=False),
    ConsumeRule("weapon_oil", "Weapon Oil", ("Wizard Oil",), note="Superior/Brilliant Wizard Oil"),
    ConsumeRule("potion", "Mana/Damage Potions", ("Super Mana Potion", "Destruction Potion")),
)

MELEE_STR_CONSUMES = (
    ConsumeRule("food", "Food", ("Roasted Clefthoof", "Spicy Hot Talbuk", "Well Fed"),
                note="+strength or +hit food"),
    ConsumeRule("flask", "Flask", ("Flask of Relentless Assault",), required=False),
    ConsumeRule("battle_elixir", "Battle Elixir",
                ("Elixir of Major Strength", "Elixir of Major Agility"), required=False),
    ConsumeRule("guardian_elixir", "Guardian Elixir",
                ("Major Fortitude", "Major Mageblood"), required=False),
    ConsumeRule("weapon_oil", "Sharpening Stone", ("Sharpening Stone", "Weightstone", "Mongoose"),
                note="Adamantite Sharpening Stone/Weightstone or a weapon enchant"),
    ConsumeRule("potion", "Potions", ("Haste Potion", "Insane Strength Potion")),
)

MELEE_AGI_CONSUMES = (
    ConsumeRule("food", "Food", ("Grilled Mudfish", "Spicy Hot Talbuk", "Well Fed"),
                note="+agility or +hit food"),
    ConsumeRule("flask", "Flask", ("Flask of Relentless Assault",), required=False),
    ConsumeRule("battle_elixir", "Battle Elixir", ("Elixir of Major Agility",), required=False),
    ConsumeRule("guardian_elixir", "Guardian Elixir",
                ("Major Fortitude", "Major Mageblood"), required=False),
    ConsumeRule("weapon_oil", "Sharpening Stone", ("Sharpening Stone", "Weightstone", "Mongoose"),
                note="Adamantite Sharpening Stone or a weapon enchant"),
    ConsumeRule("potion", "Potions", ("Haste Potion", "Insane Strength Potion")),
)

HUNTER_CONSUMES = (
    ConsumeRule("food", "Food", ("Grilled Mudfish", "Spicy Hot Talbuk", "Ravager Dog", "Well Fed"),
                note="+agility or +AP food"),
    ConsumeRule("flask", "Flask", ("Flask of Relentless Assault",), required=False),
    ConsumeRule("battle_elixir", "Battle Elixir", ("Elixir of Major Agility",), required=False),
    ConsumeRule("guardian_elixir", "Guardian Elixir",
                ("Major Fortitude", "Major Mageblood"), required=False),
    ConsumeRule("potion", "Potions", ("Haste Potion", "Insane Strength Potion")),
)


def _dps(spec: str, display: str, role: str, slots, meta: str, consumes) -> SpecProfile:
    return SpecProfile(
        spec=spec, display=display, role=role,
        enchantable_slots=slots, min_gem_quality="rare",
        meta_gem=meta, consumes=consumes,
    )


_DPS_PROFILES = [
    # ── Caster DPS ────────────────────────────────────────────────────────
    _dps("affliction_warlock", "Affliction Warlock", "caster_dps", CASTER_SLOTS, CASTER_META, CASTER_CONSUMES),
    _dps("destro_warlock", "Destruction Warlock", "caster_dps", CASTER_SLOTS, CASTER_META, CASTER_CONSUMES),
    _dps("fire_destro_warlock", "Destruction Warlock (Fire)", "caster_dps", CASTER_SLOTS, CASTER_META, CASTER_CONSUMES),
    _dps("arcane_mage", "Arcane Mage", "caster_dps", CASTER_SLOTS, CASTER_META, CASTER_CONSUMES),
    _dps("fire_mage", "Fire Mage", "caster_dps", CASTER_SLOTS, CASTER_META, CASTER_CONSUMES),
    _dps("frost_mage", "Frost Mage", "caster_dps", CASTER_SLOTS, CASTER_META, CASTER_CONSUMES),
    _dps("shadow_priest", "Shadow Priest", "caster_dps", CASTER_SLOTS, CASTER_META, CASTER_CONSUMES),
    _dps("balance_druid", "Balance Druid", "caster_dps", CASTER_SLOTS, CASTER_META, CASTER_CONSUMES),
    # ── Melee DPS ─────────────────────────────────────────────────────────
    _dps("arms_warrior", "Arms Warrior", "melee_dps", MELEE_2H_SLOTS, PHYS_META, MELEE_STR_CONSUMES),
    _dps("fury_warrior", "Fury Warrior", "melee_dps", MELEE_DW_SLOTS, PHYS_META, MELEE_STR_CONSUMES),
    _dps("ret_paladin", "Retribution Paladin", "melee_dps", MELEE_2H_SLOTS, PHYS_META, MELEE_STR_CONSUMES),
    _dps("combat_rogue", "Combat Rogue", "melee_dps", MELEE_DW_SLOTS, PHYS_META, MELEE_AGI_CONSUMES),
    _dps("assassination_rogue", "Assassination Rogue", "melee_dps", MELEE_DW_SLOTS, PHYS_META, MELEE_AGI_CONSUMES),
    _dps("enh_shaman", "Enhancement Shaman", "melee_dps", MELEE_DW_SLOTS, PHYS_META, MELEE_AGI_CONSUMES),
    _dps("feral_cat_druid", "Feral (Cat) Druid", "melee_dps", FERAL_SLOTS, PHYS_META, MELEE_AGI_CONSUMES),
    # ── Ranged physical (hunters) ─────────────────────────────────────────
    _dps("bm_hunter", "Beast Mastery Hunter", "ranged_dps", HUNTER_SLOTS, PHYS_META, HUNTER_CONSUMES),
    _dps("mm_hunter", "Marksmanship Hunter", "ranged_dps", HUNTER_SLOTS, PHYS_META, HUNTER_CONSUMES),
    _dps("survival_hunter", "Survival Hunter", "ranged_dps", HUNTER_SLOTS, PHYS_META, HUNTER_CONSUMES),
]

# ELE_SHAMAN keeps its richer hand-authored execution data; the rest fill in
# from role templates. ELE wins on key collision.
PROFILES: dict[str, SpecProfile] = {p.spec: p for p in _DPS_PROFILES}
PROFILES[ELE_SHAMAN.spec] = ELE_SHAMAN


def get_profile(spec: str) -> SpecProfile | None:
    """Return the ideal-behavior profile for a canonical spec key, or None."""
    return PROFILES.get(spec)
