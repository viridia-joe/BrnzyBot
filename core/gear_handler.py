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
from core.gear_cache import get_gear, find_gear_for_spec
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


_MARKER_LEGEND = ("_🥇 former-tier BiS (still best) · 🔥 current-tier BiS · "
                  "↔️ sidegrade to BiS · 🥈 prior-tier, within 25% of BiS · "
                  "❄️ 25–50% off BiS · 💩 50%+ off BiS_")


def _bis_marker(item_phase: int | None, current_phase: int) -> str:
    """
    Marker for a slot where the equipped item IS best-in-slot (no upgrade found):
      🥇 = BiS from an *earlier* phase (much P1 gear stays BiS deep into later tiers)
      🔥 = BiS from the *current* tier
    """
    if item_phase and current_phase and item_phase < current_phase:
        return "🥇"
    return "🔥"


def _upgrade_marker(pct_off: float, cur_phase: int | None, current_phase: int) -> str:
    """
    Marker for a slot that HAS an upgrade, graded by how far the equipped item is
    from BiS (pct_off = gain / bis_ep) with a prior-tier nuance:
      ↔️  sidegrade — essentially equal to BiS (≤5% off)
      🥈  prior-phase piece within 25% of BiS — a respectable former-tier item
      🔥  current-phase piece very close to BiS (≤10% off)
      ❄️  25–50% off BiS — a real upgrade waiting
      💩  50%+ off BiS — genuinely needs replacing
    Items with no phase data (phase 0 = dungeon/world/proc items) are graded on the
    EP gap alone — they never earn a 🥇/🥈 medal they didn't earn as raid tier gear.
    """
    if pct_off <= 0.05:
        return "↔️"                                  # sidegrade to BiS
    prior_phase = bool(cur_phase and current_phase and cur_phase < current_phase)
    if prior_phase and pct_off <= 0.25:
        return "🥈"                                  # former-tier, within 25%
    if pct_off <= 0.10:
        return "🔥"                                  # current piece, near BiS
    if pct_off <= 0.25:
        return "↔️"                                  # modest current-tier upgrade
    if pct_off <= 0.50:
        return "❄️"                                  # 25–50% off
    return "💩"                                       # 50%+ off


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

    return _upgrade_entries(opt.slots, context, snapshot)


def _upgrade_entries(opt_slots, context, snapshot) -> list[PriorityEntry]:
    """
    Turn the optimizer's optimal-set slots into ranked upgrade entries.

    IMPORTANT — value semantics: in upgrades mode the optimizer reports a swap's
    `SlotResult.ep` as the **marginal EP gain** over the item currently worn in
    that slot (base EP minus equipped EP), NOT the candidate's absolute EP. So the
    net gain is `sr.ep` directly. (A previous version did `sr.ep - cur_ep`, which
    subtracted the equipped EP a second time — net = base − 2×equipped — so an
    upgrade only surfaced if it was worth *double* the equipped item, hiding nearly
    every real upgrade and making /gearprio report "at or near BiS" always.)
    `gearcheck` (handle_gear_list) already reads `sr.ep` as the gain.
    """
    # Map slot → equipped item to display as the "from" (weaker piece for dual slots).
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
    for sr in opt_slots:
        # Only swaps are recommendations; kept/equipped items are not.
        if getattr(sr, "was_equipped", False) or sr.item_name in equipped_names:
            continue

        cur_name, cur_ep = current_ep.get(sr.slot, ("(empty)", 0.0))
        raw_net  = sr.ep                       # optimizer already gives marginal gain
        to_ep    = cur_ep + sr.ep              # reconstruct absolute EP for display
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
                to_ep=round(to_ep, 1),
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
        phase_label = _PHASE_LABELS.get(phase, f"Phase {phase}")
        lines.append(
            f"\nNo upgrades found **within {phase_label} loot** — {character} is at or near "
            f"BiS for this phase.\n"
            f"⚙️ If your guild is further along, the search is phase-gated: only "
            f"{phase_label} (and earlier) items are considered. Set the actual phase with "
            f"`/setup phase <n>` (currently **{phase}**) and re-run — later-tier upgrades "
            f"are excluded until then."
        )
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
    spec_explicit: bool = False,
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
    spec_search_note: str | None = None
    try:
        if spec_explicit:
            snapshot = find_gear_for_spec(character, realm, spec, region=region,
                                          item_db_conn=item_db)
            if snapshot is None:
                # Fall back to most-recent log with a note
                spec_search_note = (
                    f"_No {spec} logs found in last 10 reports — showing most recent log instead._"
                )
                snapshot = get_gear(character, realm, spec, region=region, item_db_conn=item_db)
        else:
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
    result = annotate(skeleton, context, node_status=node_status, phase=phase, guild_id=guild_id)
    if spec_search_note:
        result = spec_search_note + "\n\n" + result
    return result


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
    spec_explicit: bool = False,
) -> str:
    """
    Return a deterministic head-to-toe gear list comparing equipped gear vs BIS.
    No Claude. No narrative.

    verbose=True appends BiS item name, EP, and pct-off to each line.
    """
    from collections import defaultdict
    spec = resolve_spec(spec) or spec.strip().lower()

    item_db = sqlite3.connect(ITEM_DB_PATH) if os.path.exists(ITEM_DB_PATH) else None
    spec_search_note: str | None = None
    try:
        if spec_explicit:
            snapshot = find_gear_for_spec(character, realm, spec, region=region,
                                          item_db_conn=item_db)
            if snapshot is None:
                spec_search_note = (
                    f"_No {spec} logs found in last 10 reports — showing most recent log instead._"
                )
                snapshot = get_gear(character, realm, spec, region=region, item_db_conn=item_db)
        else:
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
                        # Keep 0 as 0 (no tier data) so phase-0 dungeon/world/proc
                        # items aren't mis-medaled as prior-tier raid gear.
                        equipped_phase_by_name[name] = item_phase if item_phase is not None else 0
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
        lines.append(_MARKER_LEGEND)

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

        # An equipped item that EP-scores to 0 is almost always an on-use/proc
        # effect the static EP model can't value (e.g. Quagmirran's Eye, Eye of
        # Moam). Log it to the scoring backlog for hand-scoring rather than letting
        # it read as worthless gear.
        if cur_ep == 0 and g.get("item_id"):
            try:
                from core.score_backlog import record_unscored
                record_unscored(g["item_id"], cur_name, slot, spec)
            except Exception:
                pass

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
                        mh_phase = equipped_phase_by_name.get(cur_name)
                        marker = _upgrade_marker(pct_off, mh_phase, phase)
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
                # phase 0 = no tier data (dungeon/world/proc item) → no medal,
                # graded on EP gap alone. equipped_phase_by_name stores 0 as-is now.
                cur_phase = equipped_phase_by_name.get(cur_name)
                if gain <= 0:
                    # Equipped item beats anything in the DB — it IS BiS.
                    marker = _bis_marker(cur_phase, phase)
                else:
                    marker = _upgrade_marker(pct_off, cur_phase, phase)
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

    # Gems & Enchants summary — uses the audit profiles for per-spec requirements.
    try:
        from core.audit.profiles import get_profile
        from core.audit.report import check_enchants, check_gems, check_meta
        from core.audit import gemdata
        from core.audit.checks import Verdict

        profile = get_profile(spec)
        if profile is not None and snapshot.gear:
            norm_gear, norm_gems = [], []
            meta_id, meta_socket = None, False
            for g in snapshot.gear:
                enchant_id = g.get("enchant") or None
                raw_gems = g.get("gems") or []
                slot_gems = []
                for gid in raw_gems:
                    if not gid:
                        continue
                    entry = {"quality": gemdata.gem_quality(gid), "color": gemdata.gem_color(gid), "item_id": gid, "item_level": None}
                    slot_gems.append(entry)
                    norm_gems.append(entry)
                    if gemdata.is_meta(gid):
                        meta_id = gid
                norm_gear.append({"slot": g.get("slot", ""), "item_id": g.get("item_id"), "enchant_id": enchant_id, "enchant_name": "", "gems": slot_gems})

            empty_sockets = None
            if os.path.exists(ITEM_DB_PATH):
                try:
                    import json as _json
                    idb = sqlite3.connect(ITEM_DB_PATH)
                    empty = 0
                    try:
                        cur = idb.cursor()
                        for g in norm_gear:
                            iid = g.get("item_id")
                            if not iid:
                                continue
                            row = cur.execute("SELECT sockets FROM items WHERE item_id = ?", (iid,)).fetchone()
                            if not row or not row[0]:
                                continue
                            try:
                                colors = _json.loads(row[0])
                            except (ValueError, TypeError):
                                continue
                            if any(str(c).lower() == "meta" for c in colors):
                                meta_socket = True
                            nonmeta = sum(1 for c in colors if str(c).lower() != "meta")
                            socketed = sum(1 for gm in g.get("gems", []) if not gemdata.is_meta(gm.get("item_id") or 0))
                            empty += max(0, nonmeta - socketed)
                    finally:
                        idb.close()
                    empty_sockets = empty
                except Exception as e:
                    log.debug("socket count failed: %s", e)

            _ICON = {Verdict.PASS: "✅", Verdict.INFO: "ℹ️", Verdict.WARN: "⚠️", Verdict.FAIL: "❌", Verdict.UNKNOWN: "❔"}
            enc_result  = check_enchants(norm_gear, profile)
            gem_result  = check_gems(norm_gems, profile, empty_sockets)
            meta_result = check_meta({"meta_socket": meta_socket, "meta_id": meta_id, "gems": norm_gems}, profile)
            checks = [enc_result, gem_result] + ([meta_result] if meta_result else [])
            lines.append("")
            lines.append("**Gems & Enchants**")
            for r in checks:
                lines.append(f"{_ICON.get(r.verdict, '❔')} {r.label}: {r.summary}")
    except Exception as e:
        log.debug("gems/enchants check skipped: %s", e)

    result = "\n".join(lines)
    if spec_search_note:
        result = spec_search_note + "\n\n" + result
    return result
