#!/usr/bin/env python3
"""
BrnzyBot Healer Analysis — gear-based throughput & regen check for /gearcheck.

Deterministic (no LLM). Mirrors how the rest of gear_handler works: pure logic in,
a Discord-ready markdown block out (or None when the spec isn't a healer).

Unlike DPS gear (where EP rolls everything into one number), healers care about a
few distinct axes — sustained throughput (+Healing, crit, haste) and the mana
budget to keep it up (mana pool, MP5, Spirit). We surface each against Phase-1
guide-rails from data/healer_thresholds.json.

Honesty about the data:
  - +Healing / MP5 / Spirit / Intellect are summed from EQUIPPED ITEM stats
    (the item DB), so they're gear-only — gems, enchants, and raid buffs add more.
  - Spell crit / haste use the WCL character-sheet RATING (gem/enchant-inclusive)
    and are reported as the rating's % contribution, not the character's total
    crit/haste (which also includes base + Intellect + talents + buffs).
Throughput is genuinely harder to grade from gear than tank survival is, so these
are guide-rails, not verdicts.

Entry point:
    analyze_healer(spec, snapshot) -> str | None
"""

from __future__ import annotations

import json
import logging
import os

log = logging.getLogger(__name__)

_DATA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_THRESHOLDS_PATH = os.path.join(_DATA, "healer_thresholds.json")

# +healing on TBC gear is carried by HealingPower; fall back to SpellPower for the
# rare item that only lists spell damage. (Spell-damage items list both equally.)
_HEAL_KEYS = ("HealingPower", "SpellPower")

_thresholds: dict | None = None


def _load_thresholds() -> dict:
    global _thresholds
    if _thresholds is None:
        try:
            with open(_THRESHOLDS_PATH, encoding="utf-8-sig") as f:
                _thresholds = json.load(f)
        except (FileNotFoundError, ValueError) as e:
            log.warning("healer thresholds unavailable: %s", e)
            _thresholds = {}
    return _thresholds


def is_healer(spec: str) -> bool:
    t = _load_thresholds()
    return spec in t and not spec.startswith("_")


def _sum_gear_stat(gear: list, *keys: str, per_item_fallback: bool = False) -> float:
    """Sum a stat across equipped items. With per_item_fallback, take the first
    present key PER ITEM (used for +healing: HealingPower else SpellPower)."""
    total = 0.0
    for item in gear or []:
        stats = item.get("stats") or {}
        if per_item_fallback:
            for k in keys:
                if k in stats:
                    total += float(stats.get(k, 0) or 0)
                    break
        else:
            for k in keys:
                total += float(stats.get(k, 0) or 0)
    return total


def _tier(value: float, band: dict) -> tuple[str, str]:
    """(emoji, label) for a value against {minimum, comfortable, well_geared}."""
    if value >= band["well_geared"]:
        return "🌟", "well-geared"
    if value >= band["comfortable"]:
        return "✅", "comfortable"
    if value >= band["minimum"]:
        return "🟡", "minimum"
    return "❌", f"below minimum ({band['minimum']:,})"


def analyze_healer(spec: str, snapshot) -> str | None:
    """
    Return a markdown 'Healer Analysis' block for a healer spec, or None if the
    spec isn't a healer (or thresholds/gear are unavailable).
    """
    t = _load_thresholds()
    prof = t.get(spec)
    if not prof:
        return None

    gear = getattr(snapshot, "gear", None) or []
    if not gear:
        return None

    conv = t.get("_conversions", {})
    crit_per_pct  = conv.get("spell_crit_rating_per_pct", 22.08)
    haste_per_pct = conv.get("spell_haste_rating_per_pct", 15.77)
    mana_per_int  = conv.get("mana_per_intellect", 15)

    healing = _sum_gear_stat(gear, *_HEAL_KEYS, per_item_fallback=True)
    mp5     = _sum_gear_stat(gear, "MP5")
    spirit  = _sum_gear_stat(gear, "Spirit")
    intel   = _sum_gear_stat(gear, "Intellect")
    mana_pool = prof["base_mana"] + intel * mana_per_int

    # Crit/haste: prefer the WCL sheet rating (includes gems/enchants); else gear.
    cs = getattr(snapshot, "combat_stats", None) or {}
    crit_rating  = float(cs.get("critSpell")  or _sum_gear_stat(gear, "SpellCrit"))
    haste_rating = float(cs.get("hasteSpell") or _sum_gear_stat(gear, "SpellHaste"))
    crit_pct  = crit_rating / crit_per_pct if crit_per_pct else 0.0
    haste_pct = haste_rating / haste_per_pct if haste_per_pct else 0.0

    h_emoji, h_label = _tier(healing, prof["healing"])
    p_emoji, p_label = _tier(mana_pool, prof["mana_pool"])
    m_emoji, m_label = _tier(mp5, prof["mp5"])

    lines = [
        f"**Healer Analysis — {prof['name']}**",
        f"{h_emoji} +Healing: **{healing:,.0f}** ({h_label}) — gear only; gems/enchants/buffs add more",
        f"{p_emoji} Mana pool: **{mana_pool:,.0f}** ({p_label}) — {prof['base_mana']:,} base + {intel:,.0f} Int ×{mana_per_int}",
        f"{m_emoji} MP5: **{mp5:,.0f}** ({m_label})  |  Spirit: {spirit:,.0f}",
        f"⚡ Spell crit (gear/rating): {crit_pct:.1f}%  |  haste: {haste_pct:.1f}%",
        f"_{prof['regen_note']}_",
    ]
    return "\n".join(lines)
