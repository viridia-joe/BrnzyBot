"""
BrnzyBot Gear Optimizer — Binary Integer Program for joint gear set optimization.

Formulates and solves a BIP to find the globally optimal gear set for a character,
accounting for set bonuses, hit cap, socket bonuses, slot constraints, and
profession-specific item availability.

Why a solver beats greedy slot-by-slot evaluation
──────────────────────────────────────────────────
Greedy evaluation misses cross-slot interactions. The canonical example: replacing
Mana-Etched Crown looks like +76 EP in isolation, but simultaneously replacing
Mana-Etched Spaulders in the same solve reveals you keep the 2-piece bonus and the
net is completely different. A MIP evaluates all slots jointly and finds the true
global optimum.

Formulation
───────────
Decision variables:
  x[i] ∈ {0,1}          — item i is equipped
  h ∈ [0, hit_cap]       — effective hit rating (capped; continuous)
  y[k,t] ∈ {0,1}         — set k's t-piece bonus is active

Objective (maximize):
  Σ_i x[i] * base_ep[i]           (item EP excluding hit contribution)
  + h * weight_hit                  (capped hit value)
  + Σ_{k,t} y[k,t] * bonus_ep[k,t] (set bonus EP)

Constraints:
  Σ_{i∈slot_s} x[i] ≤ capacity[s]  (slot capacity: rings/trinkets = 2)
  h ≤ Σ_i x[i] * hit[i]            (can't use hit you don't have)
  t·y[k,t] ≤ Σ_{i∈set_k} x[i]     (bonus only if enough pieces equipped)
  x[i] = 0  for items violating armor_type/class/phase constraints (bounds)

Socket bonus handling:
  Per-item, pre-compute EP with and without socket bonus (gem-matching cost
  vs bonus EP). Use whichever is higher. The threshold: if bonus EP / slots
  exceeds the EP delta of optimal-vs-matching gem, gem for it, otherwise skip.
  Meta gem (Chaotic Skyfire Diamond) assumed always active for casters — the
  2-blue-gem requirement is met naturally in any well-geared set.

Expansion awareness:
  All caps and conversion constants come from the spec file, not this module.
  Adding Wrath support means new spec files + new constraint types (ArPen cap,
  Expertise cap) using the same piecewise-linear structure as hit. No changes
  to the solver core.

Profession detection:
  Inferred from BOP crafted items currently equipped. If Brnz is wearing
  Frozen Shadoweave Robe, he is a Tailor. This is an essential truth that
  doesn't require asking.

Entry points:
  solve_bis(character, spec, db_conn, params)    -> OptimalSet
  solve_upgrades(snapshot, spec, db_conn, params) -> OptimalSet
"""

import json
import logging
import os
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from scipy.optimize import LinearConstraint, milp, Bounds
from scipy.sparse import csc_matrix

import config

log = logging.getLogger(__name__)

WEIGHTS_DIR      = config.WEIGHTS_DIR
SET_BONUSES_PATH = config.SET_BONUSES_PATH
PROFESSIONS_PATH = config.PROFESSIONS_PATH
GEMS_PATH        = config.GEMS_PATH

# Slots that allow two items simultaneously
DUAL_SLOTS = {"Ring", "Trinket"}

# Slots where no item is required (ranged / relic slot is optional in TBC)
OPTIONAL_SLOTS = {"Wand", "Ranged", "Totem", "Idol", "Libram"}

# Class → required name substring for items in the Ranged slot.
# Hunters/Warriors/Rogues can use any ranged weapon — no filter.
# All others are restricted by item name since weapon_type is unpopulated in the DB.
CLASS_RANGED_NAME_FILTER: dict[str, str | None] = {
    "Shaman":  "Totem",
    "Druid":   "Idol",
    "Paladin": "Libram",
    "Priest":  None,    # Priests use Wand slot — Ranged slot not applicable
    "Mage":    None,
    "Warlock": None,
    # Hunter, Warrior, Rogue omitted — they can equip any ranged weapon (no substring filter)
}

# Stat names that represent hit rating (expansion-agnostic names welcomed here)
HIT_STAT_NAMES = {"SpellHit", "MeleeHit", "RangedHit"}

# EP floor — items below this are excluded from the candidate set to keep the
# problem small. Set conservatively low so nothing useful is pruned.
EP_FLOOR = -999.0

# Socket bonus threshold: if the socket bonus EP per socket slot exceeds this
# fraction of the best-gem EP, gem for the bonus; otherwise go runed.
SOCKET_BONUS_THRESHOLD = 0.60   # 60% — if bonus covers 60% of a gem slot, take it


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class OptimizeParams:
    """All configuration that varies per solve. Passed into both entry points."""
    phase:             int   = 1
    hit_buff_in_raid:  bool  = False   # Shadow Priest Misery or Shaman ToW reduces cap
    fight_length_sec:  int   = 120     # 2 min default; affects healer objective weighting
    mode:              str   = "bis"   # "bis" or "upgrades"
    max_changes:       int   = 99      # for upgrades mode; 99 = unrestricted
    include_pvp:       bool  = False   # include Arena / PvP Honor gear
    include_world_boss: bool = True    # include world boss drops
    racial_hit:        int   = 0       # hit rating reduction from racial (e.g. 13 for Heroic Presence)
    gem_hit_weight:    float = -1.0   # effective hit weight for gem valuation; -1 = use spec default


@dataclass
class SlotResult:
    slot:        str
    item_id:     int
    item_name:   str
    ep:          float
    set_name:    str
    source:      str
    was_equipped: bool = False   # True if this item was in the snapshot


@dataclass
class OptimalSet:
    character:        str
    spec:             str
    expansion:        str
    total_ep:         float
    hit_rating:       float
    hit_cap:          int
    hit_status:       str
    slots:            list[SlotResult]
    active_set_bonuses: list[dict]    # [{set_name, pieces, ep}]
    profession:       Optional[str]
    solver_status:    str             # "optimal", "infeasible", "error"
    mode:             str = "bis"     # "bis" or "upgrades"
    ep_gain:          float = 0.0     # EP gain vs current gear (upgrades mode)
    warnings:         list[str] = field(default_factory=list)

    def to_discord_block(self) -> str:
        # Upgrades mode: show only the swaps, not the full 17-slot list
        if self.mode == "upgrades":
            swaps = [r for r in self.slots if not r.was_equipped]
            if not swaps:
                return (f"**{self.character}** — no upgrades found within "
                        f"{len(self.slots)} slot budget. Current gear is optimal.")
            lines = [
                f"**Top {len(swaps)} upgrade(s) over current gear — {self.character} ({self.spec})**",
                f"Total EP gain vs equipped: **+{self.ep_gain:.1f}** | "
                f"Hit after swaps: {self.hit_rating:.0f}/{self.hit_cap} ({self.hit_status})",
            ]
            if self.active_set_bonuses:
                bonus_str = ", ".join(
                    f"{b['set_name']} {b['pieces']}pc (+{b['ep']:.0f} EP)"
                    for b in self.active_set_bonuses
                )
                lines.append(f"Set bonuses active: {bonus_str}")
            lines.append("")
            for r in swaps:
                set_tag  = f" [{r.set_name}]" if r.set_name else ""
                ep_label = f"+{r.ep:.1f}" if r.ep >= 0 else f"{r.ep:.1f}"
                lines.append(f"**{r.slot}:** {r.item_name}{set_tag} ({ep_label} EP vs equipped) — {r.source}")
            lines.append("")
            lines.append("_Per-slot EP is the marginal gain over your currently equipped item. Total EP gain accounts for set bonus interactions across all swaps._")
            if self.warnings:
                lines.append("")
                for w in self.warnings:
                    lines.append(f"⚠ {w}")
            return "\n".join(lines)

        # BiS mode: full gear set
        lines = [
            f"**Optimal Gear Set — {self.character} ({self.spec})**",
            f"Total EP: **{self.total_ep:.1f}** | "
            f"Hit: {self.hit_rating:.0f}/{self.hit_cap} ({self.hit_status})",
        ]
        if self.profession:
            lines.append(f"Profession detected: {self.profession}")
        if self.active_set_bonuses:
            bonus_str = ", ".join(
                f"{b['set_name']} {b['pieces']}pc (+{b['ep']:.0f} EP)"
                for b in self.active_set_bonuses
            )
            lines.append(f"Set bonuses: {bonus_str}")
        lines.append("")
        for r in self.slots:
            set_tag = f" [{r.set_name}]" if r.set_name else ""
            lines.append(f"**{r.slot}:** {r.item_name}{set_tag} ({r.ep:.1f} EP) — {r.source}")
        if self.warnings:
            lines.append("")
            for w in self.warnings:
                lines.append(f"⚠ {w}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _load_spec(spec: str) -> dict:
    path = os.path.join(WEIGHTS_DIR, f"{spec}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Spec file not found: {path}")
    with open(path) as f:
        return json.load(f)


def _load_set_bonuses() -> dict:
    if not os.path.exists(SET_BONUSES_PATH):
        return {}
    with open(SET_BONUSES_PATH) as f:
        return json.load(f)


def _load_professions() -> dict:
    """Map of item_id → profession name for BOP crafted items."""
    if not os.path.exists(PROFESSIONS_PATH):
        return {}
    with open(PROFESSIONS_PATH) as f:
        return json.load(f)


def _load_gems() -> dict:
    if not os.path.exists(GEMS_PATH):
        return {}
    with open(GEMS_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Profession detection
# ---------------------------------------------------------------------------

def detect_profession(equipped_item_ids: list[int]) -> Optional[str]:
    """
    Infer profession from BOP crafted items currently equipped.
    An equipped Frozen Shadoweave Robe is an essential truth: the character
    is a Tailor. No inference needed beyond item ID lookup.
    """
    professions = _load_professions()
    for item_id in equipped_item_ids:
        prof = professions.get(str(item_id))
        if prof:
            return prof
    return None


# ---------------------------------------------------------------------------
# Gem and socket EP computation
# ---------------------------------------------------------------------------

def _gem_ep_for_item(
    sockets: list,
    socket_bonus: dict,
    weights: dict,
    hit_weight: float,
    gem_profile: dict,
) -> float:
    """
    Compute the optimal gem EP for an item.

    Strategy: compare EP of "gem for socket bonus" vs "go runed everywhere".
    Use whichever is higher. Threshold: if socket bonus EP per socket exceeds
    SOCKET_BONUS_THRESHOLD of the best gem's EP, gem for the bonus.

    Meta gem (Chaotic Skyfire Diamond, ~2% crit damage) assumed active.
    Its EP (~30-40 for a caster) is a character-level constant, not per-item,
    so it's added once to the objective outside this function.
    """
    if not sockets:
        return 0.0

    # Best unconstrained gem EP per socket
    best_gem_ep = _best_gem_ep_per_socket(weights, hit_weight, gem_profile)
    unconstrained_ep = best_gem_ep * len(sockets)

    # Socket bonus EP
    bonus_ep = sum(socket_bonus.get(stat, 0) * weights.get(stat, 0)
                   for stat in socket_bonus)
    # Apply hit weight override to hit stats in socket bonus
    for stat in HIT_STAT_NAMES:
        if stat in socket_bonus:
            bonus_ep += socket_bonus[stat] * (hit_weight - weights.get(stat, 0))

    if bonus_ep <= 0:
        return unconstrained_ep

    # Cost of matching: use matching color gems instead of best gems
    # Approximate: matching gems (e.g. Veiled Noble Topaz) give ~70% of a
    # Runed gem's SP contribution but add hit. We estimate the cost as
    # (n_sockets * best_gem_ep) - matching_gem_ep_total + bonus_ep
    # For simplicity: if bonus_ep >= threshold * len(sockets) * best_gem_ep,
    # the bonus pays for itself.
    bonus_per_socket = bonus_ep / len(sockets)
    if bonus_per_socket >= SOCKET_BONUS_THRESHOLD * best_gem_ep:
        # Gem for the bonus: use matching gems and collect the bonus
        # Conservative: matching gems give 70% of unconstrained EP on average
        matching_ep = unconstrained_ep * 0.70 + bonus_ep
        return max(unconstrained_ep, matching_ep)

    return unconstrained_ep


def _best_gem_ep_per_socket(weights: dict, hit_weight: float,
                             gem_profile: dict) -> float:
    """EP of the best single non-meta gem given current spec weights."""
    best = 0.0
    for color, gem in gem_profile.items():
        if not isinstance(gem, dict):
            continue
        if color.lower() == "meta":
            continue   # Meta gems only go in Meta sockets — skip here
        stats = gem.get("stats", {})
        ep = sum(stats.get(s, 0) * (hit_weight if s in HIT_STAT_NAMES
                                    else weights.get(s, 0))
                 for s in stats)
        # bonusEP on non-meta gems is rare but allowed
        if "bonusEP" in gem and color.lower() != "meta":
            ep += gem["bonusEP"]
        if ep > best:
            best = ep
    # Fallback: Runed Living Ruby = 9 SP = 9 EP at weight 1.0
    return max(best, 9.0 * weights.get("SpellPower", 1.0))


# ---------------------------------------------------------------------------
# Item candidate loading
# ---------------------------------------------------------------------------

def _load_candidates(
    db: sqlite3.Connection,
    spec_data: dict,
    params: OptimizeParams,
    equipped_ids: set,
) -> list[dict]:
    """
    Load all candidate items from the DB filtered for this spec/phase.
    Returns list of dicts with pre-computed EP values (excluding hit).
    """
    weights    = spec_data.get("weights", {})
    armor_types = spec_data.get("armor_types", [])
    class_name  = spec_data.get("class", "")
    expansion   = spec_data.get("expansion", "tbc")

    # Hit cap from spec
    hit_cap_data = spec_data.get("hit_cap", {})
    effective_cap = hit_cap_data.get("base", 202) - hit_cap_data.get("from_talents", 0) - params.racial_hit
    if params.hit_buff_in_raid:
        effective_cap -= hit_cap_data.get("raid_buff_reduction", 0)

    # Hit weight for gem calculations: use the caller-supplied effective weight when
    # available (0 if at/over cap) so hit gems aren't over-valued for capped characters.
    nominal_hit_weight = (
        params.gem_hit_weight if params.gem_hit_weight >= 0
        else weights.get("SpellHit", weights.get("MeleeHit", 0.0))
    )

    gem_data    = _load_gems()
    gem_profile = gem_data.get(_gem_profile_for_spec(spec_data), {})

    # Detect character's crafting profession from currently equipped items.
    # Used to suppress BoP crafted suggestions the character can't obtain.
    all_professions      = _load_professions()
    character_profession = detect_profession(list(equipped_ids))

    quality_filter = "quality IN ('Epic', 'Rare', 'Uncommon')"
    source_filter_parts = []
    if not params.include_pvp:
        source_filter_parts.append("source_type NOT IN ('Arena', 'PvP')")
    if not params.include_world_boss:
        source_filter_parts.append("source_type != 'World Boss'")

    source_filter = ("AND " + " AND ".join(source_filter_parts)
                     if source_filter_parts else "")

    # Equipped items must always appear as candidates regardless of source filters,
    # so the optimizer has an accurate baseline. Without this, a PvP-geared slot
    # gets treated as EP=0 and any non-PvP item looks like a massive upgrade.
    equipped_id_placeholders = ",".join("?" * len(equipped_ids)) if equipped_ids else "NULL"
    equipped_override = (
        f"OR item_id IN ({equipped_id_placeholders})" if equipped_ids else ""
    )

    c = db.cursor()
    c.execute(f"""
        SELECT item_id, name, slot, armor_type, is_unique,
               class_restriction, stats, sockets, socket_bonus,
               set_name, source_type, source_name, phase
        FROM items
        WHERE (
            ({quality_filter}
             AND phase >= 1
             AND phase <= ?
             {source_filter})
            {equipped_override}
        )
    """, (params.phase, *list(equipped_ids)))

    candidates = []
    for row in c.fetchall():
        (item_id, name, slot, armor_type, is_unique,
         class_restriction_json, stats_json, sockets_json,
         socket_bonus_json, set_name, source_type, source_name, phase) = row

        if not slot:
            continue

        # Shields: Shaman, Paladin, and Warrior can equip them in the Off Hand slot.
        # Remap before the armor-type filter so "Off Hand" exemption applies.
        if slot == "Shield":
            if class_name in {"Shaman", "Paladin", "Warrior"}:
                slot = "Off Hand"
            else:
                continue

        # Armor type filter (skip for non-armor slots)
        if (armor_types and
                slot not in ("Neck", "Back", "Ring", "Trinket", "Main Hand",
                             "Off Hand", "One Hand", "Two-Hand", "Wand",
                             "Ranged", "Relic", "Totem", "Idol", "Libram") and
                armor_type and armor_type not in armor_types):
            continue

        # Ranged slot subtype filter: Shamans can only use Totems, Druids Idols, etc.
        # weapon_type is unpopulated in the DB so we match on item name.
        if slot == "Ranged" and class_name in CLASS_RANGED_NAME_FILTER:
            required_substr = CLASS_RANGED_NAME_FILTER[class_name]
            if required_substr is None:
                continue   # class can't use the Ranged slot at all (e.g. Warlock)
            if required_substr not in name:
                continue

        # Class restriction
        try:
            cr = json.loads(class_restriction_json) if class_restriction_json else []
        except (json.JSONDecodeError, TypeError):
            cr = []
        if cr and class_name and class_name not in cr:
            continue

        # Profession filter: BoP crafted items require the character to have
        # that profession. Skip non-equipped items the character can't obtain.
        prof_required = all_professions.get(str(item_id))
        if prof_required and item_id not in equipped_ids:
            if character_profession != prof_required:
                continue

        # Stats
        try:
            stats = json.loads(stats_json) if stats_json else {}
        except (json.JSONDecodeError, TypeError):
            stats = {}

        # Sockets and socket bonus
        try:
            sockets = json.loads(sockets_json) if sockets_json else []
        except (json.JSONDecodeError, TypeError):
            sockets = []
        try:
            socket_bonus = json.loads(socket_bonus_json) if socket_bonus_json else {}
        except (json.JSONDecodeError, TypeError):
            socket_bonus = {}

        # Base EP excluding hit (hit is handled by the h variable)
        base_ep = sum(
            stats.get(s, 0) * weights.get(s, 0)
            for s in stats
            if s not in HIT_STAT_NAMES
        )

        # Raw hit rating on item (for h constraint)
        hit_rating = sum(stats.get(s, 0) for s in HIT_STAT_NAMES if s in stats)

        # Gem EP
        gem_ep = _gem_ep_for_item(
            sockets, socket_bonus, weights, nominal_hit_weight, gem_profile
        )
        base_ep += gem_ep

        if base_ep < EP_FLOOR:
            continue

        candidates.append({
            "item_id":    item_id,
            "name":       name,
            "slot":       slot,
            "set_name":   set_name or "",
            "is_unique":  bool(is_unique),
            "base_ep":    round(base_ep, 3),
            "hit_rating": hit_rating,
            "source_type": source_type or "",
            "source_name": source_name or "",
            "equipped":   item_id in equipped_ids,
        })

    log.info("Loaded %d candidate items for %s (phase %d)",
             len(candidates), spec_data.get("spec", "?"), params.phase)
    return candidates


def _gem_profile_for_spec(spec_data: dict) -> str:
    """Map spec to gem profile key in gems.json."""
    role = spec_data.get("role", "caster")
    return {
        "caster":     "caster",
        "healer":     "healer",
        "tank":       "tank",
        "melee":      "melee_phys",   # legacy alias
        "melee_phys": "melee_phys",
        "melee_str":  "melee_str",
    }.get(role, "caster")


# ---------------------------------------------------------------------------
# MIP formulation
# ---------------------------------------------------------------------------

def _build_mip(
    candidates: list[dict],
    spec_data: dict,
    set_bonuses: dict,
    params: OptimizeParams,
    spec_key: str = "",
) -> dict:
    """
    Construct the MIP problem matrices.

    Variable layout:
      [0 .. N-1]        x[i] ∈ {0,1}  — item i equipped
      [N]               h ∈ [0, cap]   — effective hit rating (continuous)
      [N+1 .. N+1+B-1]  y[k,t] ∈ {0,1} — set bonus k,t active

    Returns a dict with all arrays needed by scipy.optimize.milp.
    """
    weights   = spec_data.get("weights", {})
    hit_cap_data = spec_data.get("hit_cap", {})
    base_cap  = hit_cap_data.get("base", 202)
    from_tal  = hit_cap_data.get("from_talents", 0)
    raid_red  = hit_cap_data.get("raid_buff_reduction", 0) if params.hit_buff_in_raid else 0
    hit_cap   = base_cap - from_tal - raid_red - params.racial_hit
    hit_weight = weights.get("SpellHit", weights.get("MeleeHit", 0.0))

    N = len(candidates)
    items = candidates   # alias

    # ── Set bonus variable enumeration ─────────────────────────────────────
    # For each (set_name, threshold) pair where threshold <= max possible pieces
    slot_capacity = {s: (2 if s in DUAL_SLOTS else 1) for s in
                     set(i["slot"] for i in items)}
    set_piece_counts: dict[str, int] = {}
    for item in items:
        sn = item["set_name"]
        if sn:
            set_piece_counts[sn] = set_piece_counts.get(sn, 0) + 1

    set_bonus_vars: list[tuple[str, int, float]] = []  # (set_name, threshold, ep)
    set_bonus_hit:  list[float] = []                    # parallel: hit rating provided by each bonus
    for set_name, count in set_piece_counts.items():
        if set_name not in set_bonuses:
            continue
        bonuses_def = set_bonuses[set_name]
        for t_str, bonus in bonuses_def.items():
            if not t_str.isdigit():
                continue
            t = int(t_str)
            ep = bonus.get("ep", 0)
            if spec_key:
                ep = bonus.get("spec_overrides", {}).get(spec_key, {}).get(t_str, ep)

            bonus_stats = bonus.get("stats", {})
            if bonus_stats and all(k in HIT_STAT_NAMES for k in bonus_stats):
                # Pure-hit stat bonus (e.g. Mana-Etched 2pc): route through h variable
                # so hit past cap doesn't count. No flat EP contribution.
                hit_from_b = float(sum(bonus_stats.values()))
                non_hit_ep = 0.0
            else:
                # Non-hit or proc bonus (e.g. Cyclone 2pc SpellCrit, T5 proc):
                # keep static EP from spec_overrides or the ep field.
                hit_from_b = 0.0
                non_hit_ep = float(ep)

            if t <= count and (non_hit_ep > 0 or hit_from_b > 0):
                set_bonus_vars.append((set_name, t, non_hit_ep))
                set_bonus_hit.append(hit_from_b)

    B = len(set_bonus_vars)
    total_vars = N + 1 + B   # items + h + set bonuses

    # ── Objective: minimize negative EP (scipy minimizes) ──────────────────
    c_obj = np.zeros(total_vars)
    for i, item in enumerate(items):
        c_obj[i] = -item["base_ep"]
    c_obj[N] = -hit_weight          # h contributes hit_weight per rating
    for b, (sn, t, ep) in enumerate(set_bonus_vars):
        c_obj[N + 1 + b] = -ep

    # ── Variable bounds ─────────────────────────────────────────────────────
    lb = np.zeros(total_vars)
    ub = np.ones(total_vars)
    ub[N] = hit_cap               # h ≤ hit_cap
    lb[N] = 0.0                   # h ≥ 0

    # ── Integrality: 1=integer, 0=continuous ───────────────────────────────
    integrality = np.ones(total_vars, dtype=int)
    integrality[N] = 0             # h is continuous

    # ── Constraint matrix ──────────────────────────────────────────────────
    # We build as list of (row_data, lb, ub) then stack.
    A_rows = []
    con_lb = []
    con_ub = []

    # 1. Slot capacity: Σ_{i∈slot_s} x[i] ≤ capacity[s]
    # Weapon slots get special treatment — see hand constraint below.
    HAND_SLOTS = {"Main Hand", "Off Hand", "One Hand", "Two-Hand", "Weapon"}
    slots_seen = {}
    for i, item in enumerate(items):
        s = item["slot"]
        if s not in slots_seen:
            slots_seen[s] = []
        slots_seen[s].append(i)

    for slot, idxs in slots_seen.items():
        if slot in HAND_SLOTS:
            # Each hand slot TYPE is capped at 1 (prevents 2 Main Hand items).
            # The unified hand budget constraint below further limits total to ≤ 2.
            row = np.zeros(total_vars)
            for i in idxs:
                row[i] = 1.0
            A_rows.append(row)
            con_lb.append(-np.inf)
            con_ub.append(1.0)
            continue
        cap = 2 if slot in DUAL_SLOTS else 1
        row = np.zeros(total_vars)
        for i in idxs:
            row[i] = 1.0
        A_rows.append(row)
        con_lb.append(-np.inf)
        con_ub.append(float(cap))

    # 1b. Hand slot constraint: 2-handers use both hand slots, 1-handers use one.
    #     2 * Σ(Two-Hand ∪ Weapon) + Σ(Main Hand ∪ Off Hand ∪ One Hand) ≤ 2
    #     Prevents: staff + sword, staff + offhand, three 1H items, etc.
    hand_row = np.zeros(total_vars)
    has_hand_items = False
    for i, item in enumerate(items):
        if item["slot"] in ("Two-Hand", "Weapon"):
            hand_row[i] = 2.0
            has_hand_items = True
        elif item["slot"] in ("Main Hand", "Off Hand", "One Hand"):
            hand_row[i] = 1.0
            has_hand_items = True
    if has_hand_items:
        A_rows.append(hand_row)
        con_lb.append(-np.inf)
        con_ub.append(2.0)

    # 2. Hit constraint: h ≤ Σ_i x[i] * hit[i] + Σ_b y[b] * bonus_hit[b]
    #    Set bonus hit flows through h so it respects the hit cap.
    #    → h - Σ hit[i]*x[i] - Σ bonus_hit[b]*y[b] ≤ 0
    row = np.zeros(total_vars)
    row[N] = 1.0
    for i, item in enumerate(items):
        row[i] = -item["hit_rating"]
    for b, hit_from_b in enumerate(set_bonus_hit):
        if hit_from_b > 0:
            row[N + 1 + b] = -hit_from_b
    A_rows.append(row)
    con_lb.append(-np.inf)
    con_ub.append(0.0)

    # 3. Set bonus activation: t*y[k,t] ≤ Σ_{i∈set_k} x[i]
    #    → t*y - Σ x[i∈k] ≤ 0
    for b, (sn, t, ep) in enumerate(set_bonus_vars):
        row = np.zeros(total_vars)
        row[N + 1 + b] = float(t)
        for i, item in enumerate(items):
            if item["set_name"] == sn:
                row[i] = -1.0
        A_rows.append(row)
        con_lb.append(-np.inf)
        con_ub.append(0.0)

    # 4. Unique-equipped constraint: Σ_{i: item_id==k} x[i] ≤ 1 for unique items.
    #    Prevents recommending the same unique item in both ring/trinket slots.
    unique_id_idxs: dict[int, list[int]] = {}
    for i, item in enumerate(items):
        if item.get("is_unique"):
            uid = item["item_id"]
            unique_id_idxs.setdefault(uid, []).append(i)
    for uid, idxs in unique_id_idxs.items():
        if len(idxs) > 1:
            row = np.zeros(total_vars)
            for i in idxs:
                row[i] = 1.0
            A_rows.append(row)
            con_lb.append(-np.inf)
            con_ub.append(1.0)

    # 5. Upgrades mode: limit number of new (non-equipped) items selected.
    #    Σ_{i: not equipped} x[i] ≤ max_changes
    if params.mode == "upgrades" and params.max_changes < N:
        row = np.zeros(total_vars)
        for i, item in enumerate(items):
            if not item["equipped"]:
                row[i] = 1.0
        A_rows.append(row)
        con_lb.append(-np.inf)
        con_ub.append(float(params.max_changes))

    A = np.array(A_rows) if A_rows else np.zeros((1, total_vars))
    con_lb = np.array(con_lb)
    con_ub = np.array(con_ub)

    return {
        "c":             c_obj,
        "A":             A,
        "con_lb":        con_lb,
        "con_ub":        con_ub,
        "bounds":        Bounds(lb=lb, ub=ub),
        "integrality":   integrality,
        "hit_cap":       hit_cap,
        "hit_weight":    hit_weight,
        "set_bonus_vars": set_bonus_vars,
        "N":             N,
    }


# ---------------------------------------------------------------------------
# Solve and extract result
# ---------------------------------------------------------------------------

def _solve(problem: dict, candidates: list[dict], spec_data: dict,
           character: str, snapshot=None, params: "OptimizeParams | None" = None) -> OptimalSet:
    """Run the MIP solver and extract a human-readable OptimalSet."""
    from scipy.optimize import milp, LinearConstraint

    c    = problem["c"]
    A    = problem["A"]
    lb   = problem["con_lb"]
    ub   = problem["con_ub"]
    bnds = problem["bounds"]
    intg = problem["integrality"]
    N    = problem["N"]
    hit_cap = problem["hit_cap"]
    hit_weight = problem["hit_weight"]
    set_bonus_vars = problem["set_bonus_vars"]

    constraints = LinearConstraint(csc_matrix(A), lb, ub)
    result = milp(c, constraints=constraints, integrality=intg, bounds=bnds)

    warnings = []
    if result.status != 0:
        log.error("MIP solver status %d: %s", result.status, result.message)
        return OptimalSet(
            character=character,
            spec=spec_data.get("spec", "?"),
            expansion=spec_data.get("expansion", "tbc"),
            total_ep=0.0,
            hit_rating=0.0,
            hit_cap=hit_cap,
            hit_status="solver failed",
            slots=[],
            active_set_bonuses=[],
            profession=None,
            solver_status="error",
            warnings=[f"Solver: {result.message}"],
        )

    x = result.x

    # Extract equipped items
    slots_result: list[SlotResult] = []
    set_counts: dict[str, int] = {}
    total_hit = 0.0

    # Build slot → equipped EP lookup so we can show marginal gain per swap
    equipped_ep_by_slot: dict[str, float] = {}
    for item in candidates:
        if item["equipped"]:
            slot = item["slot"]
            # For dual slots (Ring/Trinket) sum both; for others take the single value
            equipped_ep_by_slot[slot] = equipped_ep_by_slot.get(slot, 0.0) + item["base_ep"]

    result_ids = []
    current_ep = sum(item["base_ep"] for item in candidates if item["equipped"])
    for i, item in enumerate(candidates):
        if x[i] > 0.5:
            result_ids.append(item["item_id"])
            total_hit += item["hit_rating"]
            if item["set_name"]:
                set_counts[item["set_name"]] = set_counts.get(item["set_name"], 0) + 1

            # Per-slot EP: marginal gain over what was equipped, or raw EP if nothing equipped
            slot_equipped_ep = equipped_ep_by_slot.get(item["slot"], 0.0)
            if item["equipped"]:
                slot_display_ep = item["base_ep"]
            else:
                slot_display_ep = item["base_ep"] - slot_equipped_ep

            slots_result.append(SlotResult(
                slot=item["slot"],
                item_id=item["item_id"],
                item_name=item["name"],
                ep=round(slot_display_ep, 1),
                set_name=item["set_name"],
                source=(item["source_name"] or item["source_type"] or ""),
                was_equipped=item["equipped"],
            ))

    slots_result.sort(key=lambda r: r.slot)

    # Effective hit used (h variable)
    h = x[N]
    effective_hit = min(h, total_hit)
    if abs(h - total_hit) > 1 and total_hit < hit_cap:
        warnings.append(
            f"Hit check: solver used {h:.0f} rating, gear sum {total_hit:.0f}. "
            "Check gem/enchant accounting."
        )

    # Hit status string
    overcap = max(0, total_hit - hit_cap)
    undercap = max(0, hit_cap - total_hit)
    if overcap > 0:
        hit_status = f"overcapped by {overcap:.0f} ({overcap/12.62:.1f}%)"
        warnings.append(
            f"Overcapped on hit by {overcap:.0f} rating. "
            "Consider replacing a hit item."
        )
    elif undercap > 0:
        hit_status = f"uncapped by {undercap:.0f} ({undercap/12.62:.1f}%)"
    else:
        hit_status = "at cap"

    # Active set bonuses
    set_bonuses_data = _load_set_bonuses()
    active_set_bonuses = []
    for b, (sn, t, ep) in enumerate(set_bonus_vars):
        if x[N + 1 + b] > 0.5:
            active_set_bonuses.append({
                "set_name": sn,
                "pieces":   t,
                "ep":       ep,
                "desc":     set_bonuses_data.get(sn, {}).get(str(t), {}).get("desc", ""),
            })

    # Total EP = -(objective value)
    total_ep = -result.fun

    # Profession
    profession = None
    if snapshot:
        snapshot_ids = [g.get("item_id", 0) for g in getattr(snapshot, "gear", [])]
        profession = detect_profession(snapshot_ids)

    # Warn if snapshot indicates hit but optimizer solution differs significantly
    if snapshot and hasattr(snapshot, "combat_stats"):
        weights = spec_data.get("weights", {})
        if weights.get("MeleeHit", 0) > 0:
            _wcl_hit_key = "hitMelee"
        elif weights.get("RangedHit", 0) > 0:
            _wcl_hit_key = "hitRanged"
        else:
            _wcl_hit_key = "hitSpell"
        wcl_hit = snapshot.combat_stats.get(_wcl_hit_key, 0)
        if wcl_hit and abs(wcl_hit - total_hit) > 30:
            warnings.append(
                f"Optimal set hit ({total_hit:.0f}) differs from WCL-logged hit "
                f"({wcl_hit:.0f}) — gems/enchants not fully in item DB."
            )

    ep_gain  = round(total_ep - current_ep, 1)
    mode_str = params.mode if params else "bis"

    return OptimalSet(
        character=character,
        spec=spec_data.get("spec", "?"),
        expansion=spec_data.get("expansion", "tbc"),
        total_ep=round(total_ep, 1),
        hit_rating=round(total_hit, 1),
        hit_cap=hit_cap,
        hit_status=hit_status,
        slots=slots_result,
        active_set_bonuses=active_set_bonuses,
        profession=profession,
        solver_status="optimal",
        mode=mode_str,
        ep_gain=ep_gain,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def solve_bis(
    character: str,
    spec: str,
    db: sqlite3.Connection,
    params: OptimizeParams,
    snapshot=None,
) -> OptimalSet:
    """
    Find the globally optimal gear set for this character/spec.

    Ignores current gear — pure BiS from the available item pool.
    Use solve_upgrades() to constrain the number of changes from current gear.
    """
    spec_data    = _load_spec(spec)
    set_bonuses  = _load_set_bonuses()
    equipped_ids = set()
    if snapshot:
        equipped_ids = {g.get("item_id", 0) for g in getattr(snapshot, "gear", [])}

    candidates = _load_candidates(db, spec_data, params, equipped_ids)
    if not candidates:
        return OptimalSet(
            character=character, spec=spec,
            expansion=spec_data.get("expansion", "tbc"),
            total_ep=0.0, hit_rating=0.0, hit_cap=0,
            hit_status="no candidates",
            slots=[], active_set_bonuses=[], profession=None,
            solver_status="error",
            warnings=["No candidate items found — check DB and phase."],
        )

    problem = _build_mip(candidates, spec_data, set_bonuses, params, spec_key=spec)
    return _solve(problem, candidates, spec_data, character, snapshot, params)


def solve_upgrades(
    character: str,
    spec: str,
    db: sqlite3.Connection,
    params: OptimizeParams,
    snapshot,
    max_changes: int = 5,
) -> OptimalSet:
    """
    Find the optimal gear set reachable within max_changes swaps from current gear.

    With max_changes=1: equivalent to the best single-item upgrade (like compute-upgrades.py
    but globally optimal — accounts for set bonus interactions).
    With max_changes=2: finds synergistic double-swaps (e.g. head+shoulder simultaneously
    to maintain a set bonus threshold while gaining more EP than either swap alone).
    """
    p = OptimizeParams(
        phase=params.phase,
        hit_buff_in_raid=params.hit_buff_in_raid,
        fight_length_sec=params.fight_length_sec,
        mode="upgrades",
        max_changes=max_changes,
        include_pvp=params.include_pvp,
        include_world_boss=params.include_world_boss,
    )
    return solve_bis(character, spec, db, p, snapshot)
