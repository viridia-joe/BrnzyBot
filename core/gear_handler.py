#!/usr/bin/env python3
"""
BrnzyBot Gear Handler — callable pipelines for gear commands.

Entry points for cogs/gear.py. Return strings — never post to Discord directly.

handle_gear_list(...)     — deterministic head-to-toe gear list vs BIS (/gearcheck)
handle_gear_question(...) — upgrade priority: deterministic optimizer + LLM annotation
"""

import logging
import os
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

import config
from core.gear_cache import get_gear
from core.gear_context import build_context
from core.gear_reasoning import annotate
from core.node_health import check_nodes
from core.gear_optimizer import solve_upgrades, solve_bis, OptimizeParams
from core.classifier import resolve_spec
from core.healer_analysis import analyze_healer
from db.server_config import get_guild_phase

ITEM_DB_PATH = config.ITEM_DB_PATH

_PHASE_LABELS = {1: "Phase 1", 2: "Phase 2", 3: "Phase 3", 4: "Phase 4", 5: "Phase 5"}
_DUAL_SLOTS   = {"Ring", "Trinket"}


def _bis_marker(item_phase: int | None, current_phase: int) -> str:
    """
    Front marker for a slot where the player is already wearing best-in-slot:
      🥇 = BiS from an *earlier* phase (still the best pick — much Phase-1 gear
           stays BiS deep into later tiers)
      🔥 = BiS from the *current* tier
    """
    if item_phase and current_phase and item_phase < current_phase:
        return "🥇"
    return "🔥"


# ---------------------------------------------------------------------------
# Priority entry — one upgrade candidate, fully resolved
# ---------------------------------------------------------------------------

@dataclass
class PriorityEntry:
    rank:       int
    slot:       str
    from_name:  str
    from_ep:    float
    to_name:    str
    to_ep:      float
    net_ep:     float       # true_net after set_cost
    raw_net:    float       # before set_cost
    set_cost:   float
    source:     str         # "Karazhan (Moroes)", "Crafted", etc.


def _build_upgrade_priority(character, spec, snapshot, context, phase: int = 1,
                            include_arena: bool = True) -> list[PriorityEntry]:
    """
    Run the optimizer and return a list of PriorityEntry objects sorted by
    net EP gain descending. This is the single source of truth for gearprio.
    """
    if not os.path.exists(ITEM_DB_PATH):
        return []
    # Draenei Heroic Presence: all TBC Alliance Shaman are Draenei
    is_alliance_shaman = "shaman" in spec.lower() and getattr(snapshot, "faction", -1) == 1
    racial_hit = 13 if is_alliance_shaman else 0
    params = OptimizeParams(phase=phase, include_pvp=False,
                            include_arena=include_arena,
                            include_world_boss=False, max_changes=20,
                            racial_hit=racial_hit,
                            gem_hit_weight=context.hit_cap.effective_weight)
    try:
        item_db = sqlite3.connect(ITEM_DB_PATH)
        try:
            opt = solve_upgrades(character, spec, item_db, params, snapshot, max_changes=20)
        finally:
            item_db.close()
    except Exception as e:
        log.warning("solve_upgrades failed in priority build: %s", e)
        return []

    # Map slot → weakest currently equipped item (min EP).
    # For dual slots (Ring, Trinket) we replace the weaker one.
    slot_items: dict = defaultdict(list)
    for g in context.gear_summary:
        slot_items[g["slot"]].append((g["name"], g["ep"]))
    current_ep: dict[str, tuple[str, float]] = {}
    for slot, items in slot_items.items():
        if slot in _DUAL_SLOTS and len(items) > 1:
            current_ep[slot] = min(items, key=lambda x: x[1])
        else:
            current_ep[slot] = items[0]

    equipped_names = {item["name"] for item in snapshot.gear}
    equipped_set   = {item["name"]: item.get("set_name", "") for item in snapshot.gear}

    entries = []
    for sr in opt.slots:
        cur_name, cur_ep = current_ep.get(sr.slot, ("", 0.0))
        if not cur_name or cur_name == sr.item_name:
            continue
        if sr.item_name in equipped_names:
            continue

        raw_net  = sr.ep - cur_ep
        set_name = equipped_set.get(cur_name, "")
        set_cost = context.set_bonus_cost(set_name) if set_name else 0.0
        net_ep   = raw_net - set_cost

        if net_ep > 0:
            entries.append(PriorityEntry(
                rank=0,  # assigned after sort
                slot=sr.slot,
                from_name=cur_name,
                from_ep=round(cur_ep, 1),
                to_name=sr.item_name,
                to_ep=round(sr.ep, 1),
                net_ep=round(net_ep, 1),
                raw_net=round(raw_net, 1),
                set_cost=round(set_cost, 1),
                source=sr.source or "",
            ))

    entries.sort(key=lambda e: e.net_ep, reverse=True)
    for i, e in enumerate(entries, start=1):
        e.rank = i
    return entries


def _format_priority_skeleton(character: str, spec_desc: str, context,
                               entries: list[PriorityEntry], phase: int = 1) -> str:
    """
    Format the deterministic upgrade list as a structured block that the LLM
    will annotate. The LLM must not deviate from this structure.
    """
    hc = context.hit_cap

    if hc.overcap_by > 0:
        hit_note = f"Hit: {hc.current_rating}/{hc.cap_rating} (+{hc.overcap_by} overcapped — hit EP = 0)"
    elif hc.uncapped_by > 0:
        hit_note = f"Hit: {hc.current_rating}/{hc.cap_rating} ({hc.uncapped_by} short of cap)"
    else:
        hit_note = f"Hit: {hc.current_rating}/{hc.cap_rating} (capped)"

    lines = [
        f"CHARACTER: {character} | SPEC: {spec_desc} | {_PHASE_LABELS.get(phase, f'Phase {phase}')}",
        f"HIT STATUS: {hit_note}",
    ]

    if context.active_set_bonuses:
        for sb in context.active_set_bonuses:
            cost = context.set_bonus_cost(sb.set_name)
            lines.append(
                f"ACTIVE SET: {sb.set_name} {sb.pieces_worn}pc (+{sb.ep_value:.0f} EP total, "
                f"breaking one piece costs {cost:.0f} EP)"
            )

    if not entries:
        lines.append("\nNO UPGRADES FOUND for current phase. Character is at or near BIS.")
        return "\n".join(lines)

    lines.append(f"\nRANKED UPGRADE LIST ({len(entries)} items, sorted by net EP gain):")
    for e in entries:
        net_str = f"+{e.net_ep:.1f} EP net"
        if e.set_cost > 0:
            net_str += f" (raw +{e.raw_net:.1f}, -{e.set_cost:.1f} set bonus lost)"
        src = f" | source: {e.source}" if e.source else ""
        lines.append(
            f"{e.rank}. {e.slot} | {e.from_name} ({e.from_ep:.1f}) → "
            f"{e.to_name} ({e.to_ep:.1f}) | {net_str}{src}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# /gearprio — deterministic optimizer + LLM annotation
# ---------------------------------------------------------------------------

def handle_gear_question(
    character: str,
    spec: str,
    realm: str,
    region: str = "us",
    question: str = "",
    guild_id: str = "global",
    phase_override: int | None = None,
    include_arena: bool = True,
) -> str:
    """
    Upgrade priority pipeline:
      1. Fetch gear from WCL (or cache).
      2. Run MIP optimizer → sorted PriorityEntry list (the decision).
      3. Format deterministic skeleton (rank, slot, EP delta, source).
      4. LLM annotates the skeleton with commentary (no decisions).

    The optimizer decides what to recommend and in what order.
    The LLM only adds prose: source notes, strategic context, set bonus explanations.
    """
    spec = resolve_spec(spec) or spec.strip().lower()

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

    phase    = phase_override if phase_override is not None else get_guild_phase(guild_id)
    context  = build_context(snapshot, spec)
    priority = _build_upgrade_priority(character, spec, snapshot, context, phase=phase,
                                       include_arena=include_arena)
    skeleton = _format_priority_skeleton(character, context.spec_desc, context, priority, phase=phase)

    log.info(
        "Priority built for %s (%s): %d upgrades, hit=%s",
        character, spec, len(priority), context.hit_cap.status,
    )

    node_status = check_nodes(post_alerts=False) if config.ENABLE_LLM else None
    return annotate(skeleton, context, node_status=node_status, phase=phase, guild_id=guild_id)


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

# Insert a blank line before these slots to visually group armor / jewelry / weapons
_SECTION_BREAKS = {"Ring", "Main Hand"}

_PHASE_LABELS = {1: "Phase 1", 2: "Phase 2", 3: "Phase 3", 4: "Phase 4", 5: "Phase 5"}


def handle_gear_list(
    character: str,
    spec: str,
    realm: str,
    region: str = "us",
    verbose: bool = False,
    guild_id: str = "global",
    phase_override: int | None = None,
    include_arena: bool = True,
) -> str:
    """
    Return a deterministic head-to-toe gear list comparing equipped gear vs BIS.
    No Claude. No narrative.

    verbose=True appends BiS item name, EP, and pct-off to each line.
    """
    from collections import defaultdict
    spec = resolve_spec(spec) or spec.strip().lower()

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
    phase   = phase_override if phase_override is not None else get_guild_phase(guild_id)

    # Run BIS solve for per-slot comparison
    bis_by_slot: dict[str, list] = {}
    equipped_phase_by_name: dict[str, int] = {}
    bis_ok = False
    if os.path.exists(ITEM_DB_PATH):
        try:
            item_db2 = sqlite3.connect(ITEM_DB_PATH)
            try:
                is_alliance_shaman = "shaman" in spec.lower() and getattr(snapshot, "faction", -1) == 1
                params = OptimizeParams(
                    phase=phase,
                    include_pvp=False,
                    include_arena=include_arena,
                    include_world_boss=False,
                    mode="bis",
                    racial_hit=13 if is_alliance_shaman else 0,
                    gem_hit_weight=context.hit_cap.effective_weight,
                )
                bis_result = solve_bis(character, spec, item_db2, params, snapshot=snapshot)
                if bis_result.solver_status != "error":
                    for sr in bis_result.slots:
                        bis_by_slot.setdefault(sr.slot, []).append(sr)
                    bis_ok = True
                    log.info("BIS solve slots for %s (%s): %s", character, spec,
                             {k: [r.item_name for r in v] for k, v in bis_by_slot.items()})

                # Build item_name → phase lookup for equipped items so we can
                # correctly show 🥇 vs 🔥 when the equipped item is better than
                # anything in the DB (gain < 0 case).
                equipped_ids = [g.get("item_id", 0) for g in getattr(snapshot, "gear", []) if g.get("item_id")]
                equipped_phase_by_name: dict[str, int] = {}
                if equipped_ids:
                    placeholders = ",".join("?" * len(equipped_ids))
                    rows = item_db2.execute(
                        f"SELECT name, phase FROM items WHERE item_id IN ({placeholders})",
                        equipped_ids,
                    ).fetchall()
                    for name, item_phase in rows:
                        equipped_phase_by_name[name] = item_phase or 1
            finally:
                item_db2.close()
        except Exception as e:
            log.warning("BIS solve failed for gear list: %s", e)
            equipped_phase_by_name = {}

    # Build slot → list of equipped items (preserves dual-slot order)
    equipped_by_slot: dict[str, list] = defaultdict(list)
    for g in context.gear_summary:
        equipped_by_slot[g["slot"]].append(g)

    # --- Header ---
    hc = context.hit_cap
    if hc.overcap_by > 0:
        hit_str = f"{hc.current_rating}/{hc.cap_rating} rating (**+{hc.overcap_by} over cap**)"
    elif hc.uncapped_by > 0:
        gem_note = " — gems/enchants not counted, gap may be smaller" if not hc.gems_included else ""
        hit_str = f"{hc.current_rating}/{hc.cap_rating} rating (**{hc.uncapped_by} short**{gem_note})"
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

    if verbose:
        lines.append("_🥇 BiS from an earlier phase (still best) · 🔥 current-tier BiS · ➡️ minor upgrade · ❄️ sizable upgrade_")

    lines.append("")

    # Names of all currently equipped items — used to skip BIS that's already worn
    # (e.g. unique ring recommended for both slots)
    equipped_names = {g["name"] for g in context.gear_summary}

    # Consume dual-slot entries in order
    slot_idx: dict[str, int] = {}
    bis_idx:  dict[str, int] = {}
    cur_ep_by_slot = {g["slot"]: g["ep"] for g in context.gear_summary}
    _shown_2h_name: str | None = None  # set when MH already displayed the 2H upgrade

    for slot in _SLOT_ORDER:
        items = equipped_by_slot.get(slot, [])
        i = slot_idx.get(slot, 0)
        if i >= len(items):
            continue
        slot_idx[slot] = i + 1

        # Visual breathing room between armor / jewelry / weapons sections
        if slot_idx[slot] == 1 and slot in _SECTION_BREAKS:
            lines.append("")

        g = items[i]

        cur_name = g["name"]
        cur_ep   = g["ep"]
        set_tag  = f" *[{g['set_name']}]*" if g.get("set_name") else ""

        if bis_ok:
            bi = bis_idx.get(slot, 0)
            bis_list = bis_by_slot.get(slot, [])
            sr = bis_list[bi] if bi < len(bis_list) else None
            bis_idx[slot] = bi + 1
            marker = "🔥"  # default; overwritten when an upgrade exists

            if sr is None:
                line = f"🔥 **{slot}** {cur_name}{set_tag} `{cur_ep:.1f}`"
                if slot in ("Main Hand", "Off Hand"):
                    two_hand = bis_by_slot.get("Two-Hand", []) or bis_by_slot.get("Weapon", [])
                    one_hand  = bis_by_slot.get("One Hand", [])
                    if two_hand and slot == "Main Hand":
                        two_h_sr = two_hand[0]
                        oh_ep = cur_ep_by_slot.get("Off Hand", 0.0)
                        combined_gain = two_h_sr.ep - oh_ep
                        pct_off = combined_gain / two_h_sr.ep if two_h_sr.ep > 0 else 0
                        marker = "❄️" if pct_off > 0.20 else ("➡️" if pct_off > 0.10 else "🔥")
                        if combined_gain > 0.5:
                            line = (
                                f"{marker} **{slot}** {cur_name} `{cur_ep:.1f}` "
                                f"→ {two_h_sr.item_name} (2H) **+{combined_gain:.1f}**"
                            )
                            src_str = f" — {two_h_sr.source}" if two_h_sr.source else ""
                            vdesc = (
                                f"BiS: {two_h_sr.item_name} ({two_h_sr.ep:.0f} EP, "
                                f"+{combined_gain:.1f} over MH+OH pair{src_str})"
                            )
                        else:
                            line = f"🔥 **{slot}** {cur_name} `{cur_ep:.1f}`"
                            vdesc = f"BiS ✓ ({two_h_sr.item_name} 2H is not a meaningful upgrade over MH+OH pair)"
                        _shown_2h_name = two_h_sr.item_name
                    elif two_hand and slot == "Off Hand":
                        ref = f" ({_shown_2h_name})" if _shown_2h_name else f" ({two_hand[0].item_name})"
                        vdesc = f"N/A — replaced by 2H{ref}, see Main Hand"
                    elif one_hand and slot == "Off Hand":
                        oh_sr = one_hand[0]
                        if oh_sr.was_equipped:
                            line = f"{_bis_marker(oh_sr.phase, phase)} **{slot}** {cur_name}{set_tag} `{cur_ep:.1f}`"
                        else:
                            line = f"➡️ **{slot}** {cur_name} `{cur_ep:.1f}` → {oh_sr.item_name}"
                        vdesc = "BiS ✓" if oh_sr.was_equipped else f"BiS: {oh_sr.item_name} ({oh_sr.source})"
                    else:
                        vdesc = "no BiS data"
                else:
                    vdesc = "no BiS data"
            elif sr.was_equipped:
                line = f"{_bis_marker(sr.phase, phase)} **{slot}** {cur_name}{set_tag} `{cur_ep:.1f}`"
                vdesc = "BiS ✓"
            elif sr.item_name in equipped_names:
                # BiS item is already worn in this or another slot — cur_name is
                # whatever's actually in this slot; use its phase for the marker.
                cur_phase = equipped_phase_by_name.get(cur_name, sr.phase)
                line = f"{_bis_marker(cur_phase, phase)} **{slot}** {cur_name}{set_tag} `{cur_ep:.1f}`"
                vdesc = f"BiS ({sr.item_name}) already worn"
            else:
                gain = sr.ep
                bis_ep = cur_ep + gain
                pct_off = gain / bis_ep if bis_ep > 0 else 0
                if gain <= 0:
                    # Equipped item is better than anything in the DB — it IS BiS.
                    # Use the equipped item's actual phase for the 🥇/🔥 marker.
                    cur_phase = equipped_phase_by_name.get(cur_name, phase)
                    marker = _bis_marker(cur_phase, phase)
                elif pct_off <= 0.10:
                    marker = "🔥"
                elif pct_off <= 0.20:
                    marker = "➡️"
                else:
                    marker = "❄️"
                src_str = f" — {sr.source}" if sr.source else ""
                if gain > 0.5:
                    line = (
                        f"{marker} **{slot}** {cur_name} `{cur_ep:.1f}` "
                        f"→ {sr.item_name} **+{gain:.1f}**"
                    )
                else:
                    line = f"{marker} **{slot}** {cur_name}{set_tag} `{cur_ep:.1f}`"

                if gain < 0:
                    vdesc = f"BiS ✓ (best in DB is {sr.item_name} at {bis_ep:.0f} EP — already better)"
                else:
                    vdesc = f"BiS: {sr.item_name} ({bis_ep:.0f} EP, {pct_off*100:.0f}% off{src_str})"

            if verbose:
                line = f"{line}  · _{vdesc}_"
            lines.append(line)
        else:
            lines.append(f"🔥 **{slot}** {cur_name}{set_tag} `{cur_ep:.1f}`")

    if context.warnings:
        lines.append("")
        for w in context.warnings:
            lines.append(f"⚠ {w}")

    # Healer specs get a throughput/regen section (deterministic, gear-based).
    healer_block = analyze_healer(spec, snapshot)
    if healer_block:
        lines.append("")
        lines.append(healer_block)

    return "\n".join(lines)
