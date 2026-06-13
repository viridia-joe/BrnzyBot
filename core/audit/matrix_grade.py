"""
Raid Audit Matrix — stage 2: grade a (player, fight) cell's consumables.

Turns the raw per-fight consumable auras from matrix.py into ✅ / ⚠️ / ❌ marks,
applying the role-aware philosophy from docs/RAID_AUDIT_MATRIX.md:

  - DPS: strict. The spec's best-in-slot throughput consumable is unequivocally
    best ~99% of the time, so a present-but-weaker choice is ⚠️.
  - Healers: graceful. Throughput-vs-longevity is a real judgment call you can't
    read from a parse, so any reasonable flask/elixir is ✅; only a genuinely
    absent consumable is ❌.
  - Creature-type waste (any role): a type-gated consumable (Elixir of
    Demonslaying, Consecrated Sharpening Stone) on the wrong creature type is ⚠️.

Best-in-slot convention: ConsumeRule.accepted is ORDERED — accepted[0] is the
spec's best choice, later entries are acceptable-but-suboptimal.
"""

from __future__ import annotations

from core.audit.matrix import creature_type
from core.audit.profiles import SpecProfile, get_profile

OK, SUB, MISSING, NA = "✅", "⚠️", "❌", "·"

# Type-gated consumables: name-substring → the creature type they actually help.
_TYPE_GATED = {
    "demonslaying": "Demon",
    "sharpening stone": "Undead",   # Consecrated Sharpening Stone
}


def _matches(rule_accepted, names_lower) -> tuple[bool, bool]:
    """(present, is_best). present = any accepted item is worn; is_best = the
    spec's #1 choice (accepted[0]) is worn."""
    present = any(acc.lower() in n for acc in rule_accepted for n in names_lower)
    best = bool(rule_accepted) and any(rule_accepted[0].lower() in n for n in names_lower)
    return present, best


def grade_cell(cell, boss_name: str) -> dict:
    """
    Grade one cell's consumables → {slot: (mark, label_or_consumable_name)}.
    Slots: food, flask/elixir (merged as 'elixir'), weapon_oil, potion. Uses the
    spec the player ran THIS fight (cell.spec) so a switcher is graded correctly.
    """
    out: dict = {}
    if not cell or not cell.present:
        return out
    profile: SpecProfile | None = get_profile(cell.spec) if cell.spec else None
    names_lower = [a.lower() for a in (cell.auras or [])]
    is_healer = bool(profile and profile.role == "healer")

    # --- type-gated waste check (any role) ---
    boss_type = creature_type(boss_name)
    wasted = []
    for sub, needs_type in _TYPE_GATED.items():
        if any(sub in n for n in names_lower) and boss_type != needs_type:
            wasted.append((sub, needs_type))

    if profile is None:
        # Unprofiled spec: show flask/elixir names present, no grading.
        from core.audit.profiles import FOOD_AURAS
        fe = [a for a in (cell.auras or [])
              if "flask" in a.lower() or "elixir" in a.lower()]
        ate = any(f.lower() in n for f in FOOD_AURAS for n in names_lower)
        out["elixir"] = (NA, ", ".join(fe) or "—")
        out["food"] = (OK if ate else MISSING, "")
        out["potion"] = (OK if cell.potions else NA, f"{cell.potions} used")
        return out

    # --- food ---
    food_rule = next((r for r in profile.consumes if r.slot == "food"), None)
    if food_rule:
        present, _ = _matches(food_rule.accepted, names_lower)
        out["food"] = (OK if present else MISSING, "")

    # --- weapon oil / windfury ---
    oil_rule = next((r for r in profile.consumes if r.slot == "weapon_oil"), None)
    if oil_rule:
        present, best = _matches(oil_rule.accepted, names_lower)
        if not present:
            out["weapon_oil"] = (MISSING if oil_rule.required else SUB, "")
        elif best or is_healer:
            out["weapon_oil"] = (OK, "")
        else:
            out["weapon_oil"] = (SUB, "suboptimal")

    # --- flask / elixirs (merged: a flask covers both elixir slots) ---
    flask_rule = next((r for r in profile.consumes if r.slot == "flask"), None)
    elixir_rules = [r for r in profile.consumes if r.slot in ("battle_elixir", "guardian_elixir")]
    flask_present, flask_best = _matches(flask_rule.accepted, names_lower) if flask_rule else (False, False)

    # The named flask/elixir(s) only — exclude food ("Well Fed") and non-consumable
    # buffs so the Elixirs/Flasks column shows just the relevant consumables.
    shown = [a for a in (cell.auras or [])
             if ("flask" in a.lower() or "elixir" in a.lower())
             and "well fed" not in a.lower()]
    label = ", ".join(shown) if shown else "—"

    if flask_present:
        # Healer on any flask = ✅; DPS only ✅ when it's the best flask.
        mark = OK if (flask_best or is_healer) else SUB
    elif elixir_rules:
        # No flask, check the two elixir slots are both covered.
        covered = all(_matches(r.accepted, names_lower)[0] for r in elixir_rules)
        if covered:
            # Best elixirs? best-in-slot is accepted[0] of each.
            all_best = all(_matches(r.accepted, names_lower)[1] for r in elixir_rules)
            mark = OK if (all_best or is_healer) else SUB
        else:
            mark = MISSING
    else:
        mark = MISSING if (flask_rule and flask_rule.required) else SUB

    if wasted:
        # Override to ⚠️ and annotate the wasted consumable regardless of role.
        sub, needs = wasted[0]
        mark = SUB
        label += f"  (⚠️ {sub} does nothing on {boss_name} — not {needs})"

    out["elixir"] = (mark, label)

    # --- potions ---
    pot_rule = next((r for r in profile.consumes if r.slot == "potion"), None)
    if pot_rule:
        out["potion"] = (OK if cell.potions else (SUB if not pot_rule.required else MISSING),
                         f"{cell.potions} used")

    return out
