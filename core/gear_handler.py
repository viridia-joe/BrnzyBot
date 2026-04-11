#!/usr/bin/env python3
"""
BrnzyBot Gear Handler — callable pipelines for gear commands.

Entry points for cogs/gear.py. Return strings — never post to Discord directly.

handle_gear_list(...)     — deterministic head-to-toe gear list vs BIS (/gearcheck)
handle_gear_question(...) — Claude-powered upgrade prioritization (/gearprio)
"""

import logging
import os
import sqlite3

log = logging.getLogger(__name__)

import config
from core.triage import triage
from core.gear_cache import get_gear
from core.gear_context import build_context
from core.gear_reasoning import reason
from core.node_health import check_nodes
from core.gear_optimizer import solve_upgrades, solve_bis, OptimizeParams
from core.classifier import SPEC_ALIASES

ITEM_DB_PATH = os.path.expanduser("~/.openclaw/data/tbc_items.db")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def handle_gear_question(
    character: str,
    spec: str,
    realm: str,
    region: str = "us",
    question: str = "",
) -> str:
    """
    Run the full gear analysis pipeline for a character.
    Returns a Discord-ready string. Never posts anything itself.
    """
    spec = SPEC_ALIASES.get(spec.lower(), spec.lower())
    item_db = sqlite3.connect(ITEM_DB_PATH) if os.path.exists(ITEM_DB_PATH) else None
    try:
        snapshot = get_gear(character, realm, spec, region=region, item_db_conn=item_db)
    finally:
        if item_db:
            item_db.close()

    if snapshot is None:
        return (
            f"I can't locate gear data for **{character}** right now — "
            "WCL is unreachable and no cached snapshot exists. "
            "Try again in a moment."
        )

    context = build_context(snapshot, spec)
    log.info("Context built for %s: hit_status=%s", character, context.hit_cap.status)

    # Run optimizer to get pre-computed upgrade EP values for all slots.
    # These are injected into the context so Claude uses correct EP numbers
    # instead of estimating from training knowledge.
    try:
        item_db2 = sqlite3.connect(ITEM_DB_PATH) if os.path.exists(ITEM_DB_PATH) else None
        try:
            phase = getattr(config, "CURRENT_PHASE", 1)
            params = OptimizeParams(phase=phase, include_pvp=False,
                                    include_world_boss=False, max_changes=8)
            opt = solve_upgrades(character, spec, item_db2, params, snapshot, max_changes=8)
            # Map current gear by slot for EP lookup.
            # For dual slots (Ring, Trinket), keep a list and resolve to the
            # weaker item (min EP) — that's the one we'd replace.
            from collections import defaultdict
            _DUAL_SLOTS = {"Ring", "Trinket"}
            _slot_items: dict = defaultdict(list)
            for g in context.gear_summary:
                _slot_items[g["slot"]].append((g["name"], g["ep"]))
            current_ep = {}
            for _slot, _items in _slot_items.items():
                if _slot in _DUAL_SLOTS and len(_items) > 1:
                    current_ep[_slot] = min(_items, key=lambda x: x[1])
                else:
                    current_ep[_slot] = _items[0]

            equipped_names = {item["name"] for item in snapshot.gear}
            # Build a map from item name → set_name for currently equipped gear
            equipped_set = {item["name"]: item.get("set_name", "")
                            for item in snapshot.gear}
            candidates = []
            for sr in opt.slots:
                cur_name, cur_ep = current_ep.get(sr.slot, ("", 0.0))
                if not cur_name or cur_name == sr.item_name:
                    continue
                if sr.item_name in equipped_names:
                    continue
                raw_net = sr.ep - cur_ep
                # If the current item is part of an active set bonus, swapping it
                # breaks that bonus. Subtract the breakage cost from net EP so
                # we don't recommend single-piece swaps that lose more from the
                # set than they gain from the new item.
                set_name = equipped_set.get(cur_name, "")
                set_cost = context.set_bonus_cost(set_name) if set_name else 0.0
                true_net = raw_net - set_cost
                if true_net > 0:
                    candidates.append({
                        "slot":      sr.slot,
                        "from_name": cur_name,
                        "from_ep":   cur_ep,
                        "to_name":   sr.item_name,
                        "to_ep":     round(sr.ep, 1),
                        "set_cost":  round(set_cost, 1),
                    })
            context.upgrade_candidates = candidates
            log.info("Injected %d upgrade candidates into gear context", len(candidates))
        finally:
            if item_db2:
                item_db2.close()
    except Exception as e:
        log.warning("Could not compute upgrade candidates for context: %s", e)

    node_status = check_nodes(post_alerts=False)

    # Build a minimal triage result so reason() has what it needs
    _character = character
    class _TR:
        intent = "gear_check"
        requires_gear = True
        character = _character

    answer = reason(context, _TR(), question or f"Give me a gear check for {character}.",
                    post_fn=lambda _: None, node_status=node_status)
    return answer


# ---------------------------------------------------------------------------
# Deterministic gear list — /gearcheck
# ---------------------------------------------------------------------------

_SLOT_ORDER = [
    "Head", "Neck", "Shoulder", "Back", "Chest", "Wrist",
    "Hands", "Waist", "Legs", "Feet",
    "Ring", "Ring",
    "Trinket", "Trinket",
    "Main Hand", "Off Hand", "Wand", "Ranged", "Totem",
]

_PHASE_LABELS = {1: "Phase 1", 2: "Phase 2", 3: "Phase 3", 4: "Phase 4", 5: "Phase 5"}


def handle_gear_list(
    character: str,
    spec: str,
    realm: str,
    region: str = "us",
) -> str:
    """
    Return a deterministic head-to-toe gear list comparing equipped gear vs BIS.
    No Claude. No narrative.
    """
    from collections import defaultdict
    spec = SPEC_ALIASES.get(spec.lower(), spec.lower())

    item_db = sqlite3.connect(ITEM_DB_PATH) if os.path.exists(ITEM_DB_PATH) else None
    try:
        snapshot = get_gear(character, realm, spec, region=region, item_db_conn=item_db)
    finally:
        if item_db:
            item_db.close()

    if snapshot is None:
        return (
            f"Can't locate gear data for **{character}** — "
            "WCL is unreachable and no cached snapshot exists. Try again in a moment."
        )

    context = build_context(snapshot, spec)
    phase = getattr(config, "CURRENT_PHASE", 1)

    # Run BIS solve for per-slot comparison
    bis_by_slot: dict[str, list] = {}
    bis_ok = False
    if os.path.exists(ITEM_DB_PATH):
        try:
            item_db2 = sqlite3.connect(ITEM_DB_PATH)
            try:
                params = OptimizeParams(
                    phase=phase,
                    include_pvp=False,
                    include_world_boss=False,
                    mode="bis",
                )
                bis_result = solve_bis(character, spec, item_db2, params, snapshot=snapshot)
                if bis_result.solver_status != "error":
                    for sr in bis_result.slots:
                        bis_by_slot.setdefault(sr.slot, []).append(sr)
                    bis_ok = True
            finally:
                item_db2.close()
        except Exception as e:
            log.warning("BIS solve failed for gear list: %s", e)

    # Build slot → list of equipped items (preserves dual-slot order)
    equipped_by_slot: dict[str, list] = defaultdict(list)
    for g in context.gear_summary:
        equipped_by_slot[g["slot"]].append(g)

    # --- Header ---
    hc = context.hit_cap
    if hc.overcap_by > 0:
        hit_str = f"{hc.current_rating}/{hc.cap_rating} rating (**+{hc.overcap_by} over cap**)"
    elif hc.uncapped_by > 0:
        hit_str = f"{hc.current_rating}/{hc.cap_rating} rating (**{hc.uncapped_by} short**)"
    else:
        hit_str = f"{hc.current_rating}/{hc.cap_rating} rating (capped ✓)"

    lines = [
        f"**Gear Check — {character} ({context.spec_desc})**",
        f"{_PHASE_LABELS.get(phase, f'Phase {phase}')}  |  Hit: {hit_str}",
    ]

    if context.active_set_bonuses:
        parts = [f"{sb.set_name} {sb.pieces_worn}pc (+{sb.ep_value:.0f} EP)"
                 for sb in context.active_set_bonuses]
        lines.append("Sets: " + ", ".join(parts))

    if snapshot.from_cache:
        lines.append("_⚠ Gear from cache — WCL was unavailable_")

    lines.append("")

    # Names of all currently equipped items — used to skip BIS that's already worn
    # (e.g. unique ring recommended for both slots)
    equipped_names = {g["name"] for g in context.gear_summary}

    # Consume dual-slot entries in order
    slot_idx: dict[str, int] = {}
    bis_idx:  dict[str, int] = {}

    for slot in _SLOT_ORDER:
        items = equipped_by_slot.get(slot, [])
        i = slot_idx.get(slot, 0)
        if i >= len(items):
            continue
        slot_idx[slot] = i + 1
        g = items[i]

        cur_name = g["name"]
        cur_ep   = g["ep"]
        set_tag  = f" *[{g['set_name']}]*" if g.get("set_name") else ""

        if bis_ok:
            bi = bis_idx.get(slot, 0)
            bis_list = bis_by_slot.get(slot, [])
            sr = bis_list[bi] if bi < len(bis_list) else None
            bis_idx[slot] = bi + 1

            if sr is None or sr.item_name in equipped_names:
                # No BIS data, or BIS is a unique already worn in the other slot — neutral
                lines.append(f"**{slot}** {cur_name}{set_tag} `{cur_ep:.1f}`")
            elif sr.item_name == cur_name:
                # Genuinely at BIS
                lines.append(f"**{slot}** {cur_name}{set_tag} `{cur_ep:.1f}` ✓")
            else:
                delta = sr.ep - cur_ep
                if delta > 0.5:
                    lines.append(
                        f"**{slot}** {cur_name} `{cur_ep:.1f}` "
                        f"→ {sr.item_name} **+{delta:.1f}**"
                    )
                else:
                    # Optimizer chose differently (e.g. set bonus tradeoff) — neutral
                    lines.append(f"**{slot}** {cur_name}{set_tag} `{cur_ep:.1f}`")
        else:
            lines.append(f"**{slot}** {cur_name}{set_tag} `{cur_ep:.1f}`")

    if context.warnings:
        lines.append("")
        for w in context.warnings:
            lines.append(f"⚠ {w}")

    return "\n".join(lines)
