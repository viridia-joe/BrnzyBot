"""
Raid audit — orchestrator (scaffold).

Pipeline (all deterministic; no LLM):
    WCL report URL ─▶ parse code + fight selection
                   ─▶ wcl_client: combatant info, rankings, cast table, events
                   ─▶ pure check_* functions vs the SpecProfile
                   ─▶ AuditReport.render() → Discord-ready scorecard

Status: SCAFFOLD. The check functions below are pure and unit-testable against
normalized inputs. `build_audit` wires them to core/wcl_client.py; the spots that
need a live report to finalize the exact WCL field mapping are marked TODO. See
docs/RAID_AUDIT.md for the data-source map and the implementation plan.

The check functions take already-fetched, normalized data (not the WCL client)
so they can be tested with fixtures and so the report layout can be validated
against the maintainer's example doc before any network work is finished.
"""

from __future__ import annotations

import logging
import re

from core.audit.checks import AuditReport, CheckResult, Section, Verdict
from core.audit.profiles import SpecProfile, get_profile

log = logging.getLogger(__name__)

# WCL CombatantInfo `gear` array is positional. Index → equipment slot.
GEAR_SLOTS = [
    "Head", "Neck", "Shoulder", "Shirt", "Chest", "Waist", "Legs", "Feet",
    "Wrist", "Hands", "Finger", "Finger", "Trinket", "Trinket", "Back",
    "Main Hand", "Off Hand", "Relic", "Tabard",
]


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------

_REPORT_RE = re.compile(r"reports/([A-Za-z0-9]{16})")
_FIGHT_RE = re.compile(r"[?&#]fight=(\d+|last)")


def parse_report_url(url: str) -> tuple[str | None, str | None]:
    """
    Pull the report code and (optional) fight selector out of a WCL URL.
    Accepts fresh.warcraftlogs.com / classic.warcraftlogs.com / warcraftlogs.com.
    Returns (report_code, fight_selector) where fight_selector is "12", "last",
    or None (= all fights).
    """
    code_m = _REPORT_RE.search(url or "")
    fight_m = _FIGHT_RE.search(url or "")
    return (code_m.group(1) if code_m else None,
            fight_m.group(1) if fight_m else None)


# ---------------------------------------------------------------------------
# Pure check functions — Preparation
# ---------------------------------------------------------------------------

def check_enchants(gear: list[dict], profile: SpecProfile) -> CheckResult:
    """
    gear: list of normalized slot dicts: {slot, item_id, enchant_id, enchant_name}.
    An enchant counts as present when enchant_id is truthy.
    """
    want = set(profile.enchantable_slots)
    present, missing = [], []
    seen_slots: dict[str, int] = {}
    for g in gear:
        slot = g.get("slot", "")
        if slot not in want:
            continue
        # de-dupe dual slots by occurrence
        seen_slots[slot] = seen_slots.get(slot, 0) + 1
        if g.get("enchant_id"):
            present.append(slot)
        else:
            missing.append(slot)

    have = len(present)
    total = have + len(missing)
    if total == 0:
        return CheckResult("enchants", "Enchants", Verdict.UNKNOWN,
                           "no gear/enchant data in log")
    verdict = Verdict.PASS if not missing else (Verdict.WARN if have >= total - 2 else Verdict.FAIL)
    summ = f"{have}/{total} enchantable slots"
    if missing:
        summ += f" — missing {', '.join(missing)}"
    return CheckResult("enchants", "Enchants", verdict, summ,
                       evidence={"present": present, "missing": missing})


def check_gems(gems: list[dict], profile: SpecProfile, meta_present: bool | None = None) -> CheckResult:
    """
    gems: list of {quality} dicts (quality in "uncommon"|"rare"|"epic"|...).
    Flags any gem below the profile's min quality (green/"uncommon").
    """
    if not gems:
        return CheckResult("gems", "Gems", Verdict.UNKNOWN, "no gem data in log")
    order = {"poor": 0, "common": 1, "uncommon": 2, "rare": 3, "epic": 4, "legendary": 5}
    floor = order.get(profile.min_gem_quality, 3)
    below = [g for g in gems if order.get(str(g.get("quality", "")).lower(), 99) < floor]
    total = len(gems)
    if below:
        verdict = Verdict.WARN if len(below) <= 2 else Verdict.FAIL
        summ = f"{len(below)}/{total} gems below {profile.min_gem_quality} quality"
    else:
        verdict = Verdict.PASS
        summ = f"all {total} gems {profile.min_gem_quality}+ quality"
    detail = ""
    if meta_present is False and profile.meta_gem:
        detail = f"meta gem missing — want {profile.meta_gem}"
        verdict = Verdict.WARN if verdict == Verdict.PASS else verdict
    return CheckResult("gems", "Gems", verdict, summ, detail,
                       evidence={"below": len(below), "total": total, "meta": meta_present})


def check_consumes(auras: list[dict], profile: SpecProfile, potion_count: int | None = None) -> CheckResult:
    """
    auras: buff names active at pull (from CombatantInfo) → checks food/flask/elixir/oil.
    potion_count: potions used (from cast events) — None if not yet gathered.
    A flask satisfies both elixir slots.
    """
    names = {str(a.get("name", a)).lower() for a in auras}

    def _matches(rule) -> bool:
        return any(acc.lower() in n for acc in rule.accepted for n in names)

    has_flask = any(_matches(r) for r in profile.consumes if r.slot == "flask")
    lines, worst = [], Verdict.PASS

    def _bump(v: Verdict) -> None:
        nonlocal worst
        ranks = [Verdict.PASS, Verdict.INFO, Verdict.WARN, Verdict.FAIL]
        if ranks.index(v) > ranks.index(worst):
            worst = v

    for rule in profile.consumes:
        if rule.slot == "potion":
            if potion_count is None:
                lines.append("Potions: ❔ (needs cast events)")
            else:
                ok = potion_count >= 1
                lines.append(f"Potions: {'✅' if ok else '❌'} {potion_count} used")
                _bump(Verdict.PASS if ok else Verdict.WARN)
            continue
        if rule.slot in ("battle_elixir", "guardian_elixir") and has_flask:
            continue  # flask covers elixir slots
        ok = _matches(rule)
        if not ok and not rule.required:
            continue
        lines.append(f"{rule.label}: {'✅' if ok else '❌'}")
        if not ok:
            _bump(Verdict.WARN if not rule.required else Verdict.FAIL)

    return CheckResult("consumes", "Consumes", worst, "; ".join(lines),
                       evidence={"auras": sorted(names), "has_flask": has_flask,
                                 "potion_count": potion_count})


# ---------------------------------------------------------------------------
# Pure check functions — Execution
# ---------------------------------------------------------------------------

def check_rotation(cast_counts: dict[str, int], profile: SpecProfile) -> CheckResult:
    """
    cast_counts: {spell_name: count} for the audited fights.
    Flags discouraged spells (e.g. Earth Shock as filler for ele) and confirms the
    core spells dominate.
    """
    if not cast_counts:
        return CheckResult("rotation", "Rotation", Verdict.UNKNOWN, "no cast data")
    total = sum(cast_counts.values()) or 1
    flagged = []
    for spell, reason in profile.discouraged_spells.items():
        n = cast_counts.get(spell, 0)
        # small counts are situational (movement/interrupt); a meaningful share is a habit
        if n and n / total >= 0.05:
            flagged.append((spell, n, reason))
    core_share = sum(cast_counts.get(s, 0) for s in profile.core_spells) / total
    if flagged:
        spell, n, reason = flagged[0]
        return CheckResult(
            "rotation", "Rotation", Verdict.FAIL,
            f"{spell} is {n/total:.0%} of casts — not a rotational spell",
            detail=reason,
            evidence={"cast_counts": cast_counts, "core_share": round(core_share, 3)},
        )
    verdict = Verdict.PASS if core_share >= 0.85 else Verdict.WARN
    return CheckResult("rotation", "Rotation", verdict,
                       f"core spells {core_share:.0%} of casts "
                       f"({', '.join(profile.core_spells)})",
                       evidence={"cast_counts": cast_counts, "core_share": round(core_share, 3)})


def check_activity(active_pct: float | None, profile: SpecProfile) -> CheckResult:
    if active_pct is None:
        return CheckResult("activity", "Activity", Verdict.UNKNOWN,
                           "needs cast-table active-time data")
    verdict = Verdict.PASS if active_pct >= profile.min_activity_pct else Verdict.WARN
    return CheckResult("activity", "Activity", verdict, f"{active_pct:.0f}% active",
                       evidence={"active_pct": active_pct})


def check_parse(best_pct: float | None, avg_pct: float | None) -> CheckResult:
    """Baseline parse percentile (from WCL rankings). Informational, not pass/fail."""
    if best_pct is None and avg_pct is None:
        return CheckResult("parse", "Parse %", Verdict.UNKNOWN, "no rankings for these fights")
    parts = []
    if avg_pct is not None:
        parts.append(f"avg {avg_pct:.0f}")
    if best_pct is not None:
        parts.append(f"high {best_pct:.0f}")
    return CheckResult("parse", "Parse %", Verdict.INFO, " · ".join(parts),
                       evidence={"avg": avg_pct, "best": best_pct})


# ---------------------------------------------------------------------------
# Orchestrator (integration stub)
# ---------------------------------------------------------------------------

def build_audit(url: str, character: str, spec: str) -> AuditReport:
    """
    Top-level entry: audit `character` (`spec`) in the WCL report at `url`.
    Returns an AuditReport (call .render() for Discord text).

    SCAFFOLD: the data-gathering wiring below is the integration TODO — each
    `# TODO(wcl)` shows which existing/forthcoming wcl_client call feeds the
    already-implemented pure check above. Until then we assemble a report skeleton
    with UNKNOWN checks so the layout can be validated against the example doc.
    """
    profile = get_profile(spec)
    report_code, fight_sel = parse_report_url(url)

    report = AuditReport(character=character, spec=spec,
                         report_code=report_code or "", fight_ids=[])

    if profile is None:
        report.warnings.append(f"No audit profile for spec '{spec}' yet — add one in core/audit/profiles.py.")
        return report
    if report_code is None:
        report.warnings.append("Could not parse a WCL report code from that URL.")
        return report

    # TODO(wcl): resolve fight_sel → fight_ids via wcl_client.get_fights(report_code).
    # TODO(wcl): get_master_actors → map character name → sourceID.
    # TODO(wcl): get_combatant_info(report_code, fight_id) → gear[]/auras[]; normalize
    #            gear into {slot, item_id, enchant_id, enchant_name, gems:[{quality}]}.
    # TODO(wcl): new cast-table query (table dataType:Casts) → cast_counts + active%.
    # TODO(wcl): get_rankings(report_code, fight_ids) → parse avg/best + per-fight
    #            percentiles for the movement spread (see docs/RAID_AUDIT.md).
    gear: list[dict] = []
    gems: list[dict] = []
    auras: list[dict] = []
    cast_counts: dict[str, int] = {}

    baseline = Section("Baseline")
    baseline.add(check_parse(None, None))   # TODO(wcl): rankings
    baseline.add(CheckResult("spec", "Spec", Verdict.INFO,
                             profile.standard_build_note or "—"))

    execution = Section("Execution")
    execution.add(check_activity(None, profile))      # TODO(wcl): cast table
    execution.add(check_rotation(cast_counts, profile))

    preparation = Section("Preparation")
    preparation.add(check_consumes(auras, profile))
    preparation.add(check_enchants(gear, profile))
    preparation.add(check_gems(gems, profile))

    report.sections = [baseline, execution, preparation]
    report.warnings.append(
        "Scaffold: WCL data gathering not wired yet — checks show ❔ until the "
        "`# TODO(wcl)` calls in core/audit/report.py are implemented."
    )
    return report
