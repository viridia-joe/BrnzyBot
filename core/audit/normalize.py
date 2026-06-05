"""
Raid audit — WCL CombatantInfo normalization (deterministic, no network).

The WCL ``CombatantInfo`` event carries a player's gear, gems, enchants and
at-pull auras (food/flask/elixir/oil) in a positional, lightly-typed shape. This
module turns one such record into the flat, normalized dicts the pure
``check_*`` functions in ``report.py`` expect, so the network layer and the
scoring layer stay decoupled (and the scoring stays unit-testable on fixtures).

Field mapping follows the documented WCL v2 CombatantInfo schema; everything is
parsed defensively (missing/renamed keys degrade to ❔ rather than crashing), so
the first live report can only require small tweaks here, never elsewhere.

Pipeline:  WCL CombatantInfo record ─▶ normalize_combatant() ─▶ {gear, gems,
           meta_present, auras, avg_item_level} ─▶ check_enchants/gems/consumes
"""

from __future__ import annotations

# WCL CombatantInfo `gear` is a positional array; index → equipment slot.
GEAR_SLOTS = [
    "Head", "Neck", "Shoulder", "Shirt", "Chest", "Waist", "Legs", "Feet",
    "Wrist", "Hands", "Finger", "Finger", "Trinket", "Trinket", "Back",
    "Main Hand", "Off Hand", "Relic", "Tabard",
]

# Cosmetic slots never carry a scored enchant or gem.
_COSMETIC_SLOTS = {"Shirt", "Tabard"}

# Quality ladder — must match the order in checks.check_gems.
_QUALITY_BY_RANK = ["poor", "common", "uncommon", "rare", "epic", "legendary"]

# TBC gem item-level → quality. Blue (rare) gems are ilvl 70; epic gems 110+;
# anything below 70 is a green (uncommon) gem — exactly what we want to flag.
_GEM_RARE_ILVL = 70
_GEM_EPIC_ILVL = 110

# Known meta-gem item ids. Used only to *confirm* a meta is socketed: a gem id
# we don't recognise yields meta_present=None ("unknown"), never a false
# "missing", so an incomplete list can never produce a wrong ❌. Extend freely.
META_GEM_IDS: set[int] = {
    34220,  # Chaotic Skyfire Diamond   (caster — crit damage)
    32409,  # Relentless Earthstorm Diamond (physical — crit damage)
    32410,  # Insightful Earthstorm Diamond (mana restore)
    32417,  # Powerful Earthstorm Diamond  (tank — stamina)
    35503,  # Enigmatic Skyfire Diamond    (caster — spell crit + snare reduce)
    32412,  # Mystical Skyfire Diamond
}


def _item_quality(q) -> str | None:
    """WoW item quality (int 0–5 or already a name) → quality name, or None."""
    if isinstance(q, bool):  # guard: bool is an int subclass
        return None
    if isinstance(q, int) and 0 <= q < len(_QUALITY_BY_RANK):
        return _QUALITY_BY_RANK[q]
    if isinstance(q, str) and q.lower() in _QUALITY_BY_RANK:
        return q.lower()
    return None


def _gem_quality(gem: dict) -> str | None:
    """
    Resolve a single gem's quality. Prefer an explicit ``quality`` if WCL ever
    supplies one; otherwise infer it from the gem's item level (TBC thresholds).
    Returns None when unknown so check_gems treats it as "fine" rather than a miss.
    """
    explicit = _item_quality(gem.get("quality"))
    if explicit:
        return explicit
    ilvl = gem.get("itemLevel", gem.get("item_level"))
    if isinstance(ilvl, (int, float)) and ilvl > 0:
        if ilvl >= _GEM_EPIC_ILVL:
            return "epic"
        if ilvl >= _GEM_RARE_ILVL:
            return "rare"
        return "uncommon"
    return None


def _normalize_auras(raw) -> list[dict]:
    """At-pull buffs → [{name}]. Skips entries with no resolvable name."""
    out: list[dict] = []
    for a in raw or []:
        if isinstance(a, dict):
            name = a.get("name")
        else:
            name = str(a)
        if name:
            out.append({"name": name})
    return out


def _slot_name(index: int, gear_entry: dict) -> str | None:
    """Prefer an explicit ``slot`` index if present, else positional index."""
    explicit = gear_entry.get("slot")
    if isinstance(explicit, int) and 0 <= explicit < len(GEAR_SLOTS):
        return GEAR_SLOTS[explicit]
    if 0 <= index < len(GEAR_SLOTS):
        return GEAR_SLOTS[index]
    return None


def normalize_combatant(record: dict) -> dict:
    """
    Turn one WCL CombatantInfo record into the normalized shape the checks use:

        {
          "source_id": int | None,
          "gear":  [{slot, item_id, item_quality, enchant_id, enchant_name, gems:[...]}],
          "gems":  [{quality, item_id, item_level}],   # flattened across all slots
          "meta_present": True | None,                  # never False (see above)
          "auras": [{name}],
          "avg_item_level": float | None,
        }

    Empty slots (item id 0) and cosmetic slots are dropped from gear; cosmetic
    slots are also excluded from the average item level.
    """
    gear: list[dict] = []
    gems: list[dict] = []
    meta_present: bool | None = None
    ilvls: list[float] = []

    for idx, g in enumerate(record.get("gear") or []):
        item_id = g.get("id") or 0
        if not item_id:
            continue  # empty slot
        slot = _slot_name(idx, g)
        if slot in _COSMETIC_SLOTS:
            continue

        ilvl = g.get("itemLevel", g.get("item_level"))
        if isinstance(ilvl, (int, float)) and ilvl > 0:
            ilvls.append(float(ilvl))

        slot_gems: list[dict] = []
        for gem in g.get("gems") or []:
            gid = gem.get("id") or 0
            if not gid:
                continue
            entry = {
                "quality": _gem_quality(gem),
                "item_id": gid,
                "item_level": gem.get("itemLevel", gem.get("item_level")),
            }
            slot_gems.append(entry)
            gems.append(entry)
            if gid in META_GEM_IDS:
                meta_present = True

        gear.append({
            "slot": slot,
            "item_id": item_id,
            "item_quality": _item_quality(g.get("quality")),
            "enchant_id": g.get("permanentEnchant", g.get("enchant_id")),
            "enchant_name": g.get("permanentEnchantName", g.get("enchant_name", "")),
            "gems": slot_gems,
        })

    return {
        "source_id": record.get("sourceID", record.get("source_id")),
        "gear": gear,
        "gems": gems,
        "meta_present": meta_present,
        "auras": _normalize_auras(record.get("auras")),
        "avg_item_level": round(sum(ilvls) / len(ilvls), 1) if ilvls else None,
    }
