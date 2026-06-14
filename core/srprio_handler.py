#!/usr/bin/env python3
"""
BrnzyBot Soft-Reserve Priority — /srprio <character> <raid>.

Given a character and ONE specific raid instance, list the top-5 items to
soft-reserve, ranked by how much each upgrades that character's current gear.
Answers "what should I SR in here tonight?".

Deliberately narrow (per the feature spec):
  - instance-scoped and required — only that raid's loot, no cross-raid mixing;
  - raids only (never 5-mans / heroics / world bosses);
  - up to 5 items, priority order, fewer if the raid holds fewer upgrades.

Reuses the same EP math as /gearcheck (gear_context.compute_item_ep + the spec
weights) — no MIP/scipy needed. A candidate's value is its EP minus the EP of
what the character currently wears in that slot.

Returns a Discord-ready string; the cog posts it.

NOTE: item→instance filtering relies on the item DB's source_type='Raid' +
source_name ("Zone - Boss"), populated on the live VM item DB. The committed
fixture DB has empty source columns, so end-to-end output is validated on prod;
the pure ranking/resolver logic is unit-tested offline.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3

log = logging.getLogger(__name__)

import config
from core.gear_cache import get_gear
from core.gear_context import build_context, load_spec, compute_item_ep
from core.classifier import resolve_spec

ITEM_DB_PATH = config.ITEM_DB_PATH

# Canonical TBC raids. `match` = substrings to look for in source_name (zone part);
# `aliases` = what a user might type. Keep this the single source of truth for the
# raid resolver and the loot filter.
RAIDS: dict[str, dict] = {
    "karazhan":    {"name": "Karazhan",            "match": ["Karazhan"],
                    "aliases": ["kara", "kz", "karazhan", "medivh"]},
    "gruul":       {"name": "Gruul's Lair",        "match": ["Gruul"],
                    "aliases": ["gruul", "gruuls", "gl", "gruul's lair"]},
    "magtheridon": {"name": "Magtheridon's Lair",  "match": ["Magtheridon"],
                    "aliases": ["mag", "mags", "magtheridon", "mgt", "mag's lair"]},
    "ssc":         {"name": "Serpentshrine Cavern", "match": ["Serpentshrine"],
                    "aliases": ["ssc", "serpentshrine", "serpent shrine", "vashj", "coilfang"]},
    "tk":          {"name": "Tempest Keep",        "match": ["Tempest Keep", "The Eye"],
                    "aliases": ["tk", "tempest keep", "the eye", "eye", "kael", "kael'thas"]},
    "hyjal":       {"name": "Hyjal Summit",        "match": ["Hyjal"],
                    "aliases": ["hyjal", "mh", "mount hyjal", "hyjal summit"]},
    "bt":          {"name": "Black Temple",        "match": ["Black Temple"],
                    "aliases": ["bt", "black temple", "illidan"]},
    "za":          {"name": "Zul'Aman",            "match": ["Zul'Aman"],
                    "aliases": ["za", "zulaman", "zul'aman", "zul aman", "za bears"]},
    "sunwell":     {"name": "Sunwell Plateau",     "match": ["Sunwell"],
                    "aliases": ["swp", "sunwell", "sunwell plateau", "kj", "muru"]},
}

# Equipped-gear slot names (WCL) and DB slot names → a canonical family so a
# candidate is compared against what the player wears in the same slot.
_DUAL_SLOTS = {"Ring", "Trinket"}


def _canon_slot(slot: str) -> str:
    s = (slot or "").strip().lower().rstrip("0123456789").strip()
    if s in ("finger", "ring"):
        return "Ring"
    if s == "trinket":
        return "Trinket"
    if s in ("main hand", "mainhand", "one hand", "onehand", "two-hand",
             "two hand", "twohand", "weapon"):
        return "Weapon"
    if s in ("off hand", "offhand"):
        return "OffHand"
    if s in ("ranged", "wand", "relic", "thrown"):
        return "Ranged"
    return s.title()


def resolve_raid(raw: str) -> str | None:
    """Fuzzy-resolve a user raid string to a RAIDS key, or None."""
    if not raw:
        return None
    q = raw.strip().lower()
    if q in RAIDS:
        return q
    for key, meta in RAIDS.items():
        if q == meta["name"].lower() or q in meta["aliases"]:
            return key
    # loose contains (e.g. "the eye of the storm")
    for key, meta in RAIDS.items():
        if any(a in q or q in a for a in meta["aliases"]):
            return key
    return None


def raid_choices() -> str:
    """Human-readable list of accepted raids for error messages."""
    return ", ".join(m["name"] for m in RAIDS.values())


def _load_raid_candidates(db: sqlite3.Connection, raid_key: str,
                          spec_data: dict, max_phase: int) -> list[dict]:
    """Raid-only loot usable by this spec, as candidate dicts. May be empty when
    the item DB has no source data (e.g. the fixture DB)."""
    meta = RAIDS[raid_key]
    like_clauses = " OR ".join("source_name LIKE ?" for _ in meta["match"])
    params = [f"%{m}%" for m in meta["match"]] + [max_phase]
    rows = db.execute(
        f"""SELECT name, slot, stats, source_name, phase, armor_type,
                   class_restriction, weapon_type
            FROM items
            WHERE source_type IN ('Raid', '25-man Raid', '10-man Raid', 'Raid10')
              AND ({like_clauses})
              AND phase <= ?
              AND quality IN ('Epic', 'Legendary', 'Rare')""",
        params,
    ).fetchall()

    spec_class = (spec_data.get("class") or "").strip()
    armor_types = set(spec_data.get("armor_types") or [])
    weapon_types = set(spec_data.get("weapon_types") or [])
    # Real weapon types we validate proficiency on (matches gear_optimizer).
    real_weapon_types = {"Mace", "Sword", "Axe", "Dagger", "Fist", "Polearm",
                         "Staff", "Gun", "Bow", "Crossbow", "Thrown", "Wand"}
    out = []
    for name, slot, stats_json, source_name, phase, armor_type, class_restr, weapon_type in rows:
        try:
            cr = json.loads(class_restr or "[]")
        except ValueError:
            cr = []
        if cr and spec_class and spec_class not in cr:
            continue
        if armor_type and armor_types and armor_type not in armor_types:
            continue
        # Weapon proficiency: skip weapons (and the Wand slot) the spec can't wield
        # so e.g. an Elemental Shaman isn't soft-reserve-recommended a wand.
        if weapon_types:
            if weapon_type in real_weapon_types and weapon_type not in weapon_types:
                continue
            if slot == "Wand" and "Wand" not in weapon_types:
                continue
        try:
            stats = json.loads(stats_json or "{}")
        except ValueError:
            stats = {}
        out.append({"name": name, "slot": slot, "stats": stats,
                    "source_name": source_name or meta["name"], "phase": phase})
    return out


def _equipped_ep_by_slot(context) -> dict[str, float]:
    """Canonical slot → baseline EP to beat (the weaker item for dual slots)."""
    by_slot: dict[str, list[float]] = {}
    for g in context.gear_summary:
        by_slot.setdefault(_canon_slot(g["slot"]), []).append(g["ep"])
    baseline = {}
    for slot, eps in by_slot.items():
        # To upgrade a dual slot you replace your weaker piece.
        baseline[slot] = min(eps) if slot in _DUAL_SLOTS else max(eps)
    return baseline


def rank_candidates(candidates: list[dict], equipped_ep_by_slot: dict[str, float],
                    spec_data: dict, hit_status, limit: int = 5) -> list[dict]:
    """Score each candidate's marginal EP vs current gear; return top `limit`
    upgrades (gain > 0), one entry per item, highest gain first."""
    ranked, seen = [], set()
    for c in candidates:
        if c["name"] in seen:
            continue
        ep = compute_item_ep(c["stats"], spec_data, hit_status)
        base = equipped_ep_by_slot.get(_canon_slot(c["slot"]), 0.0)
        gain = ep - base
        if gain <= 0:
            continue
        seen.add(c["name"])
        ranked.append({"name": c["name"], "slot": c["slot"],
                       "source": c["source_name"], "ep": ep, "gain": gain})
    ranked.sort(key=lambda x: x["gain"], reverse=True)
    return ranked[:limit]


def _boss_of(source_name: str, raid_name: str) -> str:
    """'Karazhan - Moroes' → 'Moroes'; fall back to the raid name."""
    if source_name and " - " in source_name:
        return source_name.split(" - ", 1)[1]
    return source_name or raid_name


def handle_srprio(character: str, spec: str, realm: str, raid: str,
                  region: str = "us", guild_id: str = "global",
                  phase_override: int | None = None) -> str:
    """Top-5 soft-reserve picks for a character in one raid. Returns a string."""
    raid_key = resolve_raid(raid)
    if not raid_key:
        return (f"Don't recognize the raid **{raid}**. Soft reserve is raids only — "
                f"try one of: {raid_choices()}.")
    rname = RAIDS[raid_key]["name"]

    spec = resolve_spec(spec) or spec.strip().lower()
    if not os.path.exists(ITEM_DB_PATH):
        return "Item database not found — the optimizer/SR feature needs a populated item DB."

    from core.gear_optimizer import solve_upgrades, OptimizeParams
    from core import phase as _phase
    meta = RAIDS[raid_key]

    # Only this raid's loot is swap-able; everything else of the character's gear
    # stays fixed. The optimizer still optimizes the WHOLE set, so the hit cap and
    # set bonuses are handled correctly (a swap that would drop you below the hit
    # cap won't be recommended - the greedy per-slot ranker couldn't see that).
    def _raid_filter(item: dict) -> bool:
        if (item.get("source_type") or "") not in (
                "Raid", "25-man Raid", "10-man Raid", "Raid10"):
            return False
        src = item.get("source_name") or ""
        return any(m.lower() in src.lower() for m in meta["match"])

    item_db = sqlite3.connect(ITEM_DB_PATH)
    try:
        snapshot = get_gear(character, realm, spec, region=region, item_db_conn=item_db)
        if snapshot is None:
            return (f"Can't locate gear data for **{character}** — WCL is unreachable and "
                    "no cached snapshot exists. Try again in a moment.")
        context = build_context(snapshot, spec)
        ceiling = _phase.resolve_for_guild(guild_id, override=phase_override).content_phase_max
        is_alliance_shaman = "shaman" in spec.lower() and getattr(snapshot, "faction", -1) == 1
        params = OptimizeParams(
            phase=ceiling, include_pvp=False, include_arena=True,
            include_world_boss=False, mode="upgrades",
            racial_hit=13 if is_alliance_shaman else 0,
            gem_hit_weight=context.hit_cap.effective_weight,
        )
        # max_changes large enough to surface every worthwhile raid upgrade.
        opt = solve_upgrades(character, spec, item_db, params, snapshot,
                             max_changes=10, candidate_filter=_raid_filter)
    finally:
        item_db.close()

    if opt.solver_status == "error":
        return (f"No **{rname}** loot found for {character}'s class/spec in the item DB. "
                "(If the DB has no source data yet, that's expected until it's enriched on the host.)")

    # The optimizer's non-equipped slot results ARE the raid swaps (the filter
    # confined new picks to this raid). Rank by marginal EP gain, top 5.
    swaps = sorted((sr for sr in opt.slots if not sr.was_equipped and sr.ep > 0.5),
                   key=lambda sr: sr.ep, reverse=True)[:5]

    # At/over the hit cap: hit past cap is worth 0 EP, so hit-heavy pieces won't
    # surface as upgrades. Flag this so a near-cap raider isn't confused.
    capped = not context.hit_cap.hit_is_valuable
    cap_note = (
        "\n_You're at the spell hit cap, so hit-heavy pieces are valued at zero "
        "and won't show as upgrades - that's correct, not a bug._" if capped else ""
    )

    if not swaps:
        return (f"**SR Priority — {character} ({context.spec_desc}) · {rname}**\n"
                f"Nothing in **{rname}** is an upgrade over what **{character}** already "
                f"wears - totally normal once you're geared. Reserve freely, or check "
                f"another raid.{cap_note}")

    lines = [f"**SR Priority — {character} ({context.spec_desc}) · {rname}**"]
    for i, sr in enumerate(swaps, 1):
        boss = _boss_of(sr.source, rname)
        lines.append(f"{i}. **{sr.item_name}** ({boss}) — +{sr.ep:.0f} EP  · _{sr.slot}_")
    if len(swaps) < 5:
        lines.append(f"_(only {len(swaps)} upgrade{'s' if len(swaps) != 1 else ''} "
                     f"in {rname} for this gear - normal when you're well-geared)_")
    lines.append(cap_note.lstrip("\n") if cap_note else "")
    return "\n".join(l for l in lines if l)
