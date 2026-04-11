"""
BrnzyBot Gear Context — deterministic pre-computation for gear reasoning.

This module runs BEFORE any model is called. It assembles everything a reasoning
model needs to answer a gear question correctly: hit cap status, active set bonuses,
socket values, and a resolved character identity.

The model must not re-derive these facts. It receives them as computed truth.
Confusing the physics of one spec with another is not tolerated — every value
here is isolated to (expansion, spec, talent_build, current_gear_state).

Entry point:
    build_context(snapshot, spec_data, set_bonuses) -> GearContext
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

WEIGHTS_DIR    = os.path.expanduser("~/.openclaw/data/weights")
SET_BONUSES_PATH = os.path.expanduser("~/.openclaw/data/set_bonuses.json")
RULINGS_PATH   = os.path.expanduser("~/.openclaw/workspace/gear_rulings.md")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class HitCapStatus:
    cap_rating:       int     # effective cap for this spec in this raid context
    base_cap:         int     # from spec file (no raid buffs)
    from_talents:     int     # hit% from talents (already subtracted from base)
    current_rating:   int     # sum of gear hit rating
    overcap_by:       int     # > 0 means wasted hit
    uncapped_by:      int     # > 0 means still needs hit
    effective_weight: float   # SpellHit EP weight to use in calculations

    @property
    def status(self) -> str:
        if self.overcap_by > 0:
            return f"overcapped by {self.overcap_by} rating ({self.overcap_by / 12.62:.1f}%)"
        if self.uncapped_by > 0:
            return f"uncapped by {self.uncapped_by} rating ({self.uncapped_by / 12.62:.1f}%)"
        return "exactly at cap"

    @property
    def hit_is_valuable(self) -> bool:
        return self.uncapped_by > 0


@dataclass
class ActiveSetBonus:
    set_name:    str
    pieces_worn: int
    ep_value:    float   # total EP from all active bonus tiers
    bonuses:     list    # list of {threshold, desc, ep}
    slots:       list    # which slots have this set piece


@dataclass
class GearContext:
    character:       str
    realm:           str
    spec:            str
    spec_desc:       str
    expansion:       str    # "tbc", "wrath", etc. — from spec file or default
    hit_cap:         HitCapStatus
    active_set_bonuses: list[ActiveSetBonus]
    total_set_ep:    float  # sum of all active set bonus EP
    gear_summary:    list   # [{slot, name, ep, set_name}]
    from_cache:      bool
    rulings:         str    # contents of gear_rulings.md, empty if none
    warnings:        list[str] = field(default_factory=list)
    upgrade_candidates: list[dict] = field(default_factory=list)
    # [{slot, from_name, from_ep, to_name, to_ep}] — pre-computed by optimizer

    def set_bonus_cost(self, set_name: str) -> float:
        """Return EP that would be lost by removing one piece of a set."""
        for sb in self.active_set_bonuses:
            if sb.set_name == set_name:
                # EP at N pieces vs EP at N-1 pieces
                n = sb.pieces_worn
                ep_at_n = sum(b["ep"] for b in sb.bonuses if b["threshold"] <= n)
                ep_at_n_minus_1 = sum(b["ep"] for b in sb.bonuses if b["threshold"] <= n - 1)
                return ep_at_n - ep_at_n_minus_1
        return 0.0

    def to_prompt_block(self) -> str:
        """Render this context as a structured block for injection into model prompts."""
        import config as _cfg
        current_phase = getattr(_cfg, "CURRENT_PHASE", 1)
        phase_labels = {1: "Phase 1 (Karazhan / Gruul's Lair / Magtheridon)",
                        2: "Phase 2 (SSC / TK)",
                        3: "Phase 3 (Hyjal / Black Temple)",
                        4: "Phase 4 (Zul'Aman)",
                        5: "Phase 5 (Sunwell Plateau)"}
        phase_label = phase_labels.get(current_phase, f"Phase {current_phase}")

        lines = [
            f"## Gear Context: {self.character} — {self.spec_desc}",
            "",
            f"**Expansion:** {self.expansion.upper()}",
            f"**Current Server Phase:** {phase_label}",
            "  ⚠ Only recommend items available in this phase or earlier. Do NOT suggest items from later phases.",
            f"**From cache:** {'Yes (WCL unavailable)' if self.from_cache else 'No (live WCL data)'}",
            "",
            "### Hit Cap Status",
            f"- Spec cap: {self.hit_cap.base_cap} rating"
            + (f" (reduced by {self.hit_cap.from_talents} from talents" if self.hit_cap.from_talents else ""),
            f"- Current gear hit: {self.hit_cap.current_rating} rating",
            f"- Status: **{self.hit_cap.status}**",
            f"- SpellHit EP weight to use: **{self.hit_cap.effective_weight:.2f}**",
            "  ⚠ Hit over cap is worth ZERO EP. Do not recommend hit items if overcapped.",
            "",
            "### Active Set Bonuses",
        ]

        if self.active_set_bonuses:
            for sb in self.active_set_bonuses:
                lines.append(f"**{sb.set_name}** ({sb.pieces_worn}-piece, {sb.ep_value:.1f} EP total)")
                for b in sb.bonuses:
                    if b["threshold"] <= sb.pieces_worn:
                        lines.append(f"  - {b['threshold']}-piece: {b['desc']} ({b['ep']:.1f} EP)")
                lines.append(f"  Breaking one piece costs: **{self.set_bonus_cost(sb.set_name):.1f} EP**")
                lines.append("")
        else:
            lines.append("No active set bonuses.")
            lines.append("")

        lines.append("### Current Gear")
        for g in self.gear_summary:
            set_tag = f" [{g['set_name']}]" if g.get("set_name") else ""
            lines.append(f"- {g['slot']}: {g['name']}{set_tag} (EP {g['ep']:.1f})")

        if self.upgrade_candidates:
            lines.append("")
            lines.append("### Pre-computed Upgrade Candidates")
            lines.append("⚠ These EP values were calculated with spec weights and hit cap correction.")
            lines.append("  Use them as ground truth. Do NOT re-calculate item EP from first principles.")
            for uc in self.upgrade_candidates:
                raw_net = uc['to_ep'] - uc['from_ep']
                set_cost = uc.get('set_cost', 0.0)
                true_net = raw_net - set_cost
                net_str = f"+{true_net:.1f} EP"
                if set_cost > 0:
                    net_str += f" (raw +{raw_net:.1f}, minus {set_cost:.1f} set bonus lost)"
                lines.append(
                    f"- {uc['slot']}: {uc['from_name']} ({uc['from_ep']:.1f} EP) → "
                    f"{uc['to_name']} ({uc['to_ep']:.1f} EP), net {net_str}"
                )

        if self.warnings:
            lines.append("")
            lines.append("### Warnings")
            for w in self.warnings:
                lines.append(f"⚠ {w}")

        if self.rulings:
            lines.append("")
            lines.append("### Established Rulings (apply these)")
            lines.append(self.rulings)

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------
def load_spec(spec: str) -> dict | None:
    path = os.path.join(WEIGHTS_DIR, f"{spec}.json")
    if not os.path.exists(path):
        log.error("Spec file not found: %s", path)
        return None
    with open(path) as f:
        return json.load(f)


def load_set_bonuses() -> dict:
    if not os.path.exists(SET_BONUSES_PATH):
        return {}
    with open(SET_BONUSES_PATH) as f:
        return json.load(f)


def load_rulings() -> str:
    if not os.path.exists(RULINGS_PATH):
        return ""
    with open(RULINGS_PATH) as f:
        return f.read().strip()


# ---------------------------------------------------------------------------
# Hit cap computation
# ---------------------------------------------------------------------------
def compute_hit_cap(snapshot, spec_data: dict) -> HitCapStatus:
    """
    Compute hit cap status from current gear and spec file.

    All hit values in TBC are in rating (not percent).
    12.62 hit rating = 1% hit at level 70.
    """
    hit_cap_data = spec_data.get("hit_cap", {})
    base_cap     = hit_cap_data.get("base", 202)      # default TBC spell hit cap
    from_talents = hit_cap_data.get("from_talents", 0)
    effective_cap = base_cap - from_talents

    # Determine which hit stat applies to this spec from its weights.
    # Melee specs weight MeleeHit; ranged weight RangedHit; casters weight SpellHit.
    weights = spec_data.get("weights", {})
    if weights.get("MeleeHit", 0) > 0:
        hit_stat_item = "MeleeHit"
        hit_stat_wcl  = "hitMelee"
    elif weights.get("RangedHit", 0) > 0:
        hit_stat_item = "RangedHit"
        hit_stat_wcl  = "hitRanged"
    else:
        hit_stat_item = "SpellHit"
        hit_stat_wcl  = "hitSpell"

    # Sum hit rating from all equipped items
    gear_sum = 0
    for item in snapshot.gear:
        gear_sum += int(item.get("stats", {}).get(hit_stat_item, 0))

    # WCL combat stats include the character's actual rating (with gems/enchants).
    # When available and the gap vs the item DB sum is large (>20 rating), prefer
    # WCL as it's the ground truth for what the character actually has on.
    wcl_hit = snapshot.combat_stats.get(hit_stat_wcl, 0)
    if wcl_hit and abs(wcl_hit - gear_sum) > 20:
        log.info(
            "Using WCL hit rating %d (gear DB sum %d, gap likely gems/enchants).",
            wcl_hit, gear_sum,
        )
        current_rating = int(wcl_hit)
    else:
        current_rating = gear_sum

    overcap  = max(0, current_rating - effective_cap)
    uncapped = max(0, effective_cap - current_rating)

    # Hit weight goes to zero at cap
    nominal_weight = spec_data.get("weights", {}).get("SpellHit", 0.0)
    effective_weight = nominal_weight if uncapped > 0 else 0.0

    return HitCapStatus(
        cap_rating=effective_cap,
        base_cap=base_cap,
        from_talents=from_talents,
        current_rating=current_rating,
        overcap_by=overcap,
        uncapped_by=uncapped,
        effective_weight=effective_weight,
    )


# ---------------------------------------------------------------------------
# Set bonus computation
# ---------------------------------------------------------------------------
def compute_active_set_bonuses(snapshot, set_bonuses: dict) -> list[ActiveSetBonus]:
    """
    Identify which set bonuses are active given the character's current gear.
    """
    # Count pieces per set and track which slots
    set_counts: dict[str, dict] = {}
    for item in snapshot.gear:
        sn = item.get("set_name", "")
        if not sn:
            continue
        if sn not in set_counts:
            set_counts[sn] = {"count": 0, "slots": []}
        set_counts[sn]["count"] += 1
        set_counts[sn]["slots"].append(item["slot"])

    active = []
    for set_name, info in set_counts.items():
        n = info["count"]
        if set_name not in set_bonuses:
            continue

        bonuses_def = set_bonuses[set_name]
        active_bonuses = []
        total_ep = 0.0

        for threshold_str, bonus in bonuses_def.items():
            if not threshold_str.isdigit():
                continue
            threshold = int(threshold_str)
            ep = bonus.get("ep", 0)
            desc = bonus.get("desc", "")
            active_bonuses.append({
                "threshold": threshold,
                "desc":      desc,
                "ep":        ep,
            })
            if threshold <= n:
                total_ep += ep

        active_bonuses.sort(key=lambda x: x["threshold"])

        # Only include sets where at least one bonus tier is active
        if total_ep > 0:
            active.append(ActiveSetBonus(
                set_name=set_name,
                pieces_worn=n,
                ep_value=total_ep,
                bonuses=active_bonuses,
                slots=info["slots"],
            ))

    active.sort(key=lambda x: -x.ep_value)
    return active


# ---------------------------------------------------------------------------
# Item EP computation (with hit cap correction)
# ---------------------------------------------------------------------------
def compute_item_ep(stats: dict, spec_data: dict, hit_status: HitCapStatus) -> float:
    """
    Compute EP for an item's stats, applying the correct hit weight.

    Uses hit_status.effective_weight instead of the spec file weight when
    the character is at or over the hit cap — hit past cap is worth nothing.
    """
    weights = dict(spec_data.get("weights", {}))
    weights["SpellHit"] = hit_status.effective_weight
    return sum(stats.get(k, 0) * v for k, v in weights.items())


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def build_context(snapshot, spec: str) -> GearContext:
    """
    Build a fully-resolved GearContext from a gear snapshot and spec name.

    This is the mandatory pre-step for all gear reasoning. No model call
    should happen before this returns.
    """
    warnings = []

    spec_data = load_spec(spec)
    if not spec_data:
        spec_data = {"weights": {}, "hit_cap": {}, "spec": spec}
        warnings.append(f"Spec file '{spec}' not found — EP values will be zero.")

    set_bonuses = load_set_bonuses()
    rulings     = load_rulings()

    hit_status   = compute_hit_cap(snapshot, spec_data)
    active_sets  = compute_active_set_bonuses(snapshot, set_bonuses)
    total_set_ep = sum(sb.ep_value for sb in active_sets)

    if snapshot.from_cache:
        warnings.append("WCL was unavailable — gear data is from cache, may not reflect recent changes.")

    if hit_status.overcap_by > 20:
        warnings.append(
            f"Overcapped on hit by {hit_status.overcap_by} rating "
            f"({hit_status.overcap_by / 12.62:.1f}%). "
            "Consider replacing hit items."
        )

    # Gear summary with EP values using corrected hit weight
    gear_summary = []
    for item in snapshot.gear:
        ep = compute_item_ep(item.get("stats", {}), spec_data, hit_status)
        gear_summary.append({
            "slot":     item["slot"],
            "name":     item["name"],
            "item_id":  item["item_id"],
            "ep":       round(ep, 1),
            "set_name": item.get("set_name", ""),
        })

    return GearContext(
        character=snapshot.character,
        realm=snapshot.realm,
        spec=spec,
        spec_desc=spec_data.get("spec", spec),
        expansion=spec_data.get("expansion", "tbc"),
        hit_cap=hit_status,
        active_set_bonuses=active_sets,
        total_set_ep=total_set_ep,
        gear_summary=gear_summary,
        from_cache=snapshot.from_cache,
        rulings=rulings,
        warnings=warnings,
    )
