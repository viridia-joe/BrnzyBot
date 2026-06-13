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
    # Healers: a trailing silence (no casts) this many seconds before the kill is
    # flagged as indicative of going OOM. 0 = don't check (DPS/tanks).
    end_silence_warn_sec: float = 0.0

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
# Food buff aura NAMES as they appear in WCL combat data. Most TBC (Outland)
# food shows the generic "Well Fed"; legacy Vanilla cooking foods still use their
# original stat-named auras. "Well Fed" and "Enlightened" (Skullfish Soup, +20
# spell crit) are confirmed against live Dreamscythe logs; the rest are from
# research (Wowhead TBC). Skullfish is a crit/longevity pick — a small throughput
# loss vs raw +spell-damage food, but a legitimate "ate food" signal.
FOOD_AURAS = (
    "Well Fed",
    "Enlightened",            # Skullfish Soup (+20 spell crit, +20 spirit)
    "Mana Regeneration",      # Smoked Sagefish / Sagefish Delight / Nightfin Soup
    "Health Regeneration",    # Tender Wolf Steak (+stam/spirit)
    "Increased Intellect",    # Runn Tum Tuber Surprise
    "Increased Stamina", "Increased Agility", "Increased Strength", "Increased Spirit",
    "Stormchops", "Electrified",   # Stormchops proc food (no stats; recognized, not flagged)
)

_ARMOR_SLOTS   = ("Head", "Shoulder", "Back", "Chest", "Wrist", "Hands", "Legs", "Feet")
CASTER_SLOTS   = _ARMOR_SLOTS + ("Main Hand",)
MELEE_2H_SLOTS = _ARMOR_SLOTS + ("Main Hand",)            # 2H weapon occupies Main Hand
MELEE_DW_SLOTS = _ARMOR_SLOTS + ("Main Hand", "Off Hand")
FERAL_SLOTS    = _ARMOR_SLOTS                              # weapon enchants don't work in forms
HUNTER_SLOTS   = _ARMOR_SLOTS + ("Relic",)                # Relic index = ranged weapon (scope)

CASTER_CONSUMES = (
    ConsumeRule("food", "Food", FOOD_AURAS,
                note="most food shows 'Well Fed'; some legacy foods show named buffs"),
    ConsumeRule("flask", "Flask",
                ("Flask of Supreme Power", "Flask of Pure Death", "Flask of Blinding Light"),
                required=False, note="A flask satisfies both elixir slots."),
    # Buff names as they appear in the log: Adept's Elixir → "Spellpower Elixir";
    # Elixir of Major Firepower → "Major Firepower"; etc.
    ConsumeRule("battle_elixir", "Battle Elixir",
                ("Spellpower Elixir", "Adept's Elixir", "Major Firepower",
                 "Major Shadow Power", "Felmight"), required=False),
    ConsumeRule("guardian_elixir", "Guardian Elixir",
                ("Draenic Wisdom", "Major Mageblood"), required=False),
    # Superior Wizard Oil (+42 SP) is BiS for nearly all casters; Brilliant
    # (+36 SP / +14 crit) is acceptable. accepted[0] = best for DPS grading.
    ConsumeRule("weapon_oil", "Weapon Oil",
                ("Superior Wizard Oil", "Brilliant Wizard Oil",
                 "Superior Mana Oil", "Brilliant Mana Oil"),
                required=False, note="Superior Wizard Oil is best; Brilliant is acceptable."),
    ConsumeRule("potion", "Mana/Damage Potions", ("Super Mana Potion", "Destruction Potion"),
                required=False),
)

MELEE_STR_CONSUMES = (
    ConsumeRule("food", "Food", FOOD_AURAS,
                note="+strength or +hit food"),
    ConsumeRule("flask", "Flask", ("Flask of Relentless Assault",), required=False),
    ConsumeRule("battle_elixir", "Battle Elixir",
                ("Elixir of Major Strength", "Elixir of Major Agility"), required=False),
    ConsumeRule("guardian_elixir", "Guardian Elixir",
                ("Major Fortitude", "Major Mageblood"), required=False),
    ConsumeRule("weapon_oil", "Sharpening Stone", ("Sharpening Stone", "Weightstone"),
                note="Adamantite Sharpening Stone (bladed) or Weightstone (blunt) — stacks with a permanent enchant"),
    ConsumeRule("potion", "Potions", ("Haste Potion", "Insane Strength Potion")),
)

MELEE_AGI_CONSUMES = (
    ConsumeRule("food", "Food", FOOD_AURAS,
                note="+agility or +hit food"),
    ConsumeRule("flask", "Flask", ("Flask of Relentless Assault",), required=False),
    ConsumeRule("battle_elixir", "Battle Elixir", ("Elixir of Major Agility",), required=False),
    ConsumeRule("guardian_elixir", "Guardian Elixir",
                ("Major Fortitude", "Major Mageblood"), required=False),
    ConsumeRule("weapon_oil", "Sharpening Stone", ("Sharpening Stone", "Weightstone"),
                note="Adamantite Sharpening Stone (bladed) or Weightstone (blunt) — stacks with a permanent enchant"),
    ConsumeRule("potion", "Potions", ("Haste Potion", "Insane Strength Potion")),
)

HUNTER_CONSUMES = (
    ConsumeRule("food", "Food", FOOD_AURAS,
                note="+agility or +AP food"),
    ConsumeRule("flask", "Flask", ("Flask of Relentless Assault",), required=False),
    ConsumeRule("battle_elixir", "Battle Elixir", ("Elixir of Major Agility",), required=False),
    ConsumeRule("guardian_elixir", "Guardian Elixir",
                ("Major Fortitude", "Major Mageblood"), required=False),
    ConsumeRule("potion", "Potions", ("Haste Potion", "Insane Strength Potion")),
)


HEALER_META = "Insightful Earthstorm Diamond"   # mana restore proc

HEALER_CONSUMES = (
    ConsumeRule("food", "Food", FOOD_AURAS,
                note="+healing or +spirit food"),
    ConsumeRule("flask", "Flask", ("Flask of Mighty Restoration",), required=False,
                note="Mighty Restoration (+25 mp5), or run double elixirs"),
    ConsumeRule("battle_elixir", "Battle Elixir",
                ("Elixir of Healing Power", "Elixir of Mastery"), required=False),
    ConsumeRule("guardian_elixir", "Guardian Elixir",
                ("Major Mageblood", "Draenic Wisdom"), required=False),
    ConsumeRule("weapon_oil", "Mana Oil", ("Mana Oil",),
                note="Superior/Brilliant Mana Oil (healers use mana oil, not wizard oil)"),
    ConsumeRule("potion", "Mana Potions", ("Super Mana Potion",)),
)


TANK_META = "Powerful Earthstorm Diamond"   # +stamina meta

# Shield tanks (warrior/paladin): stamina/hit food, fort or threat flask,
# defense/agi elixirs, sharpening stone for threat (optional — many run a
# permanent weapon enchant instead).
TANK_CONSUMES = (
    ConsumeRule("food", "Food", FOOD_AURAS,
                note="+stamina (Fisherman's Feast) or +hit (threat) food"),
    ConsumeRule("flask", "Flask", ("Flask of Fortification", "Flask of Relentless Assault"),
                required=False, note="Fortification (survival) or Relentless Assault (threat)"),
    ConsumeRule("battle_elixir", "Battle Elixir",
                ("Elixir of Major Defense", "Elixir of Major Agility"), required=False),
    ConsumeRule("guardian_elixir", "Guardian Elixir",
                ("Elixir of Major Fortitude", "Major Mageblood", "Ironskin"), required=False),
    ConsumeRule("weapon_oil", "Sharpening Stone", ("Sharpening Stone", "Weightstone"),
                required=False, note="threat — or a permanent weapon enchant"),
    ConsumeRule("potion", "Potions", ("Ironshield Potion", "Super Mana Potion",
                                      "Haste Potion", "Major Healing Potion")),
)

# Bear tanks: no weapon enchant/stone works in form, so no weapon-buff slot.
BEAR_TANK_CONSUMES = (
    ConsumeRule("food", "Food", FOOD_AURAS,
                note="+stamina or +agility food"),
    ConsumeRule("flask", "Flask", ("Flask of Fortification", "Flask of Relentless Assault"),
                required=False),
    ConsumeRule("battle_elixir", "Battle Elixir",
                ("Elixir of Major Agility", "Elixir of Major Defense"), required=False),
    ConsumeRule("guardian_elixir", "Guardian Elixir",
                ("Elixir of Major Fortitude", "Major Mageblood"), required=False),
    ConsumeRule("potion", "Potions", ("Haste Potion", "Major Healing Potion", "Ironshield Potion")),
)


def _dps(spec: str, display: str, role: str, slots, meta: str, consumes) -> SpecProfile:
    return SpecProfile(
        spec=spec, display=display, role=role,
        enchantable_slots=slots, min_gem_quality="rare",
        meta_gem=meta, consumes=consumes,
    )


def _healer(spec: str, display: str) -> SpecProfile:
    return SpecProfile(
        spec=spec, display=display, role="healer",
        enchantable_slots=CASTER_SLOTS, min_gem_quality="rare",
        meta_gem=HEALER_META, consumes=HEALER_CONSUMES,
        end_silence_warn_sec=15.0,
    )


def _tank(spec: str, display: str, slots, consumes) -> SpecProfile:
    return SpecProfile(
        spec=spec, display=display, role="tank",
        enchantable_slots=slots, min_gem_quality="rare",
        meta_gem=TANK_META, consumes=consumes,
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

# ── Healers ───────────────────────────────────────────────────────────────
# Healing is judged differently from DPS: downranking is an accepted mana
# tool (so we never flag low ranks), and throughput matters less than mana
# management and keeping the raid alive. Preparation is the base; the
# end-of-fight silence check (Execution) is the one behavioural signal — a long
# quiet stretch before the kill is indicative of going OOM.
_HEALER_PROFILES = [
    _healer("holy_paladin", "Holy Paladin"),
    _healer("holy_priest", "Holy Priest"),
    _healer("resto_druid", "Restoration Druid"),
    _healer("resto_shaman", "Restoration Shaman"),
]

# ── Tanks ───────────────────────────────────────────────────────────────────
# Preparation-focused like DPS, but with survival consumes and the +stamina meta.
# Shield tanks carry weapon + shield (Off Hand) enchants; bears carry no weapon
# enchant (forms). No end-of-fight silence check — for a tank, going quiet means
# death/threat-drop, a different signal than a healer's OOM.
_TANK_PROFILES = [
    _tank("prot_warrior", "Protection Warrior", MELEE_DW_SLOTS, TANK_CONSUMES),
    _tank("prot_paladin", "Protection Paladin", MELEE_DW_SLOTS, TANK_CONSUMES),
    _tank("feral_bear_druid", "Feral (Bear) Druid", FERAL_SLOTS, BEAR_TANK_CONSUMES),
]

# ELE_SHAMAN keeps its richer hand-authored execution data; the rest fill in
# from role templates. ELE wins on key collision.
PROFILES: dict[str, SpecProfile] = {
    p.spec: p for p in _DPS_PROFILES + _HEALER_PROFILES + _TANK_PROFILES
}
PROFILES[ELE_SHAMAN.spec] = ELE_SHAMAN


def get_profile(spec: str) -> SpecProfile | None:
    """Return the ideal-behavior profile for a canonical spec key, or None."""
    return PROFILES.get(spec)
