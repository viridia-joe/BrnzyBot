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

from core.audit.checks import AuditReport, CheckResult, RosterAudit, Section, Verdict
from core.audit.normalize import normalize_combatant
from core.audit.profiles import SpecProfile, get_profile

log = logging.getLogger(__name__)


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

# Enchant severity by slot. Missing a MAJOR enchant is a real stat loss; missing
# only MINOR enchants is closer to A → A+. Validated against TBC values: weapon,
# helm, legs, shoulders (and a hunter's ranged scope, slot "Relic") are the heavy
# hitters; chest/boots/wrist/hands/back/off-hand are comparatively small.
MAJOR_ENCHANT_SLOTS = {"Head", "Legs", "Shoulder", "Main Hand", "Off Hand", "Relic"}

_VERDICT_RANK = {Verdict.PASS: 0, Verdict.INFO: 1, Verdict.WARN: 2, Verdict.FAIL: 3}


def _worst(a: Verdict, b: Verdict) -> Verdict:
    return a if _VERDICT_RANK.get(a, 0) >= _VERDICT_RANK.get(b, 0) else b


def check_enchants(gear: list[dict], profile: SpecProfile) -> CheckResult:
    """
    gear: list of normalized slot dicts: {slot, item_id, enchant_id, enchant_name}.
    An enchant counts as present when enchant_id is truthy.

    Missing a MAJOR enchant (weapon, helm, legs, shoulders, hunter ranged scope)
    is a real stat loss → FAIL. Missing only MINOR enchants (chest, boots, wrist,
    hands, back, off-hand) is closer to A → A+ → WARN.
    """
    want = set(profile.enchantable_slots)
    present, missing_major, missing_minor = [], [], []
    for g in gear:
        slot = g.get("slot", "")
        if slot not in want:
            continue
        if g.get("enchant_id"):
            present.append(slot)
        elif slot in MAJOR_ENCHANT_SLOTS:
            missing_major.append(slot)
        else:
            missing_minor.append(slot)

    have = len(present)
    total = have + len(missing_major) + len(missing_minor)
    if total == 0:
        return CheckResult("enchants", "Enchants", Verdict.UNKNOWN,
                           "no gear/enchant data in log")
    if missing_major:
        verdict = Verdict.FAIL
    elif missing_minor:
        verdict = Verdict.WARN
    else:
        verdict = Verdict.PASS
    summ = f"{have}/{total} enchantable slots enchanted"
    parts = []
    if missing_major:
        parts.append(f"missing major: {', '.join(missing_major)}")
    if missing_minor:
        parts.append(f"missing minor: {', '.join(missing_minor)}")
    if parts:
        summ += " — " + "; ".join(parts)
    detail = ""
    if missing_major:
        detail = ("Major slots (weapon, helm, legs, shoulders) are big stat gains. "
                  "Minor slots like chest/boots are closer to A → A+.")
    return CheckResult("enchants", "Enchants", verdict, summ, detail,
                       evidence={"present": present, "missing_major": missing_major,
                                 "missing_minor": missing_minor})


def check_gems(gems: list[dict], profile: SpecProfile,
               meta_present: bool | None = None,
               empty_sockets: int | None = None) -> CheckResult:
    """
    gems: list of {quality} dicts (quality in "uncommon"|"rare"|"epic"|...).
    Flags empty sockets, gems below the profile's min quality (green/"uncommon"),
    and a missing meta gem. empty_sockets is computed against the item DB's socket
    counts (None when that data isn't available → simply not checked).
    """
    if not gems and empty_sockets is None and meta_present is None:
        return CheckResult("gems", "Gems", Verdict.UNKNOWN, "no gem/socket data in log")

    order = {"poor": 0, "common": 1, "uncommon": 2, "rare": 3, "epic": 4, "legendary": 5}
    floor = order.get(profile.min_gem_quality, 3)
    below = [g for g in gems if order.get(str(g.get("quality", "")).lower(), 99) < floor]
    total = len(gems)

    verdict = Verdict.PASS
    issues: list[str] = []
    if empty_sockets:
        issues.append(f"{empty_sockets} empty socket{'s' if empty_sockets != 1 else ''}")
        verdict = _worst(verdict, Verdict.WARN if empty_sockets <= 2 else Verdict.FAIL)
    if below:
        issues.append(f"{len(below)}/{total} gems below {profile.min_gem_quality} quality")
        verdict = _worst(verdict, Verdict.WARN if len(below) <= 2 else Verdict.FAIL)
    if meta_present is False and profile.meta_gem:
        issues.append(f"meta gem missing — want {profile.meta_gem}")
        verdict = _worst(verdict, Verdict.WARN)

    if issues:
        summ = "; ".join(issues)
    elif total:
        summ = f"all {total} gems {profile.min_gem_quality}+ quality, sockets filled"
    else:
        summ = "sockets filled" if empty_sockets == 0 else "no gems socketed"
    return CheckResult("gems", "Gems", verdict, summ,
                       evidence={"below": len(below), "total": total,
                                 "meta": meta_present, "empty_sockets": empty_sockets})


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
# Per-combatant assembly (pure: takes already-normalized data)
# ---------------------------------------------------------------------------

def audit_combatant(
    character: str,
    spec: str,
    profile: SpecProfile,
    data: dict,
    report_code: str = "",
    fight_ids: list[int] | None = None,
) -> AuditReport:
    """
    Build the Preparation scorecard (plus a free Baseline iLvl line) for one
    raider from a normalized CombatantInfo dict (see normalize.normalize_combatant).

    This is the first shippable cut: enchants / gems / consumes need nothing
    beyond CombatantInfo. Execution (rotation/activity) and the parse-% Baseline
    follow when the cast-table and rankings queries land — see docs/RAID_AUDIT.md.
    """
    report = AuditReport(character=character, spec=spec,
                         report_code=report_code, fight_ids=fight_ids or [])

    ilvl = data.get("avg_item_level")
    baseline = Section("Baseline")
    baseline.add(CheckResult("ilvl", "Gear iLvl", Verdict.INFO,
                             f"{ilvl:.0f} avg equipped" if ilvl else "—"))

    preparation = Section("Preparation")
    preparation.add(check_consumes(data.get("auras", []), profile))
    preparation.add(check_enchants(data.get("gear", []), profile))
    preparation.add(check_gems(data.get("gems", []), profile,
                               meta_present=data.get("meta_present"),
                               empty_sockets=data.get("empty_sockets")))

    report.sections = [baseline, preparation]
    return report


# ---------------------------------------------------------------------------
# WCL gathering (the only network in this module)
# ---------------------------------------------------------------------------

def _count_empty_sockets(gear: list[dict]) -> int | None:
    """
    Empty (ungemmed) non-meta sockets across equipped gear, using the item DB's
    socket counts vs. the gems actually socketed. Returns None when the item DB
    isn't present (e.g. dev box) so the gem check skips empty-socket scoring
    rather than guessing.
    """
    import json as _json
    import os as _os
    import sqlite3 as _sqlite3

    import config
    from core.audit.normalize import META_GEM_IDS

    if not _os.path.exists(config.ITEM_DB_PATH):
        return None
    try:
        conn = _sqlite3.connect(config.ITEM_DB_PATH)
    except _sqlite3.Error:
        return None
    empty = 0
    try:
        cur = conn.cursor()
        for g in gear:
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
            nonmeta_sockets = sum(1 for c in colors if str(c).lower() != "meta")
            socketed = sum(1 for gm in (g.get("gems") or [])
                           if gm.get("item_id") not in META_GEM_IDS)
            empty += max(0, nonmeta_sockets - socketed)
    finally:
        conn.close()
    return empty


def _fight_label(fight: dict) -> str:
    name = fight.get("name", "fight")
    return f"{name} ({'kill' if fight.get('kill') else 'wipe'})"


def _select_fight(fights: list[dict], fight_sel: str | None) -> dict | None:
    """
    Pick the fight whose at-pull snapshot we audit. An explicit ?fight=N wins;
    otherwise prefer the longest *kill* (most representative of a fully-prepped
    pull), falling back to the longest fight of any kind.
    """
    if not fights:
        return None
    if fight_sel and fight_sel.isdigit():
        fid = int(fight_sel)
        for f in fights:
            if f.get("id") == fid:
                return f
    kills = [f for f in fights if f.get("kill")]
    pool = kills or fights
    return max(pool, key=lambda f: f.get("endTime", 0) - f.get("startTime", 0))


def _gather(report_code: str, fight_sel: str | None):
    """Return (fight, combatants, actors_by_id) for the selected fight, or raise."""
    from core import wcl_client

    fights = wcl_client.get_fights(report_code)
    fight = _select_fight(fights, fight_sel)
    if fight is None:
        return None, [], {}
    actors = wcl_client.get_master_actors(report_code)
    combatants = wcl_client.get_combatant_info(report_code, fight["id"])
    actors_by_id = {a.get("id"): a for a in actors}
    return fight, combatants, actors_by_id


# ---------------------------------------------------------------------------
# Orchestrators
# ---------------------------------------------------------------------------

def build_audit(url: str, character: str, spec: str) -> AuditReport:
    """
    Audit a single `character` (`spec`) in the WCL report at `url`.
    Returns an AuditReport (call .render() for Discord text). Deterministic.
    """
    profile = get_profile(spec)
    report_code, fight_sel = parse_report_url(url)
    report = AuditReport(character=character, spec=spec,
                         report_code=report_code or "", fight_ids=[])

    if profile is None:
        report.warnings.append(
            f"No audit profile for spec '{spec}' yet — add one in core/audit/profiles.py."
        )
        return report
    if report_code is None:
        report.warnings.append("Could not parse a WCL report code from that URL.")
        return report

    try:
        fight, combatants, actors_by_id = _gather(report_code, fight_sel)
    except Exception as exc:  # network / WCL errors are surfaced, not raised
        log.exception("audit fetch failed for %s", character)
        report.warnings.append(f"WCL fetch failed: {exc}")
        return report

    if fight is None:
        report.warnings.append("No fights found in that report.")
        return report

    name_to_id = {str(a.get("name", "")).lower(): a.get("id")
                  for a in actors_by_id.values()}
    target_id = name_to_id.get(character.lower())
    rec = next((r for r in combatants if r.get("sourceID") == target_id), None)
    if rec is None:
        report.warnings.append(
            f"{character} not found in {_fight_label(fight)} — were they in this pull?"
        )
        return report

    norm = normalize_combatant(rec)
    norm["empty_sockets"] = _count_empty_sockets(norm.get("gear", []))
    return audit_combatant(character, spec, profile, norm,
                           report_code=report_code, fight_ids=[fight["id"]])


def build_roster_audit(url: str, resolve_spec) -> RosterAudit:
    """
    Audit every profiled raider in the report at `url`.

    `resolve_spec(name, wow_class) -> spec | None` maps a logged player to a
    canonical spec key (the cog supplies one backed by the guild's character
    registry). Players with no spec, or a spec we have no profile for, are
    listed under `skipped` rather than dropped silently.
    """
    report_code, fight_sel = parse_report_url(url)
    roster = RosterAudit(report_code=report_code or "")

    if report_code is None:
        roster.warnings.append("Could not parse a WCL report code from that URL.")
        return roster

    try:
        fight, combatants, actors_by_id = _gather(report_code, fight_sel)
    except Exception as exc:
        log.exception("roster audit fetch failed")
        roster.warnings.append(f"WCL fetch failed: {exc}")
        return roster

    if fight is None:
        roster.warnings.append("No fights found in that report.")
        return roster
    roster.fight_label = _fight_label(fight)

    seen: set[str] = set()
    for rec in combatants:
        norm = normalize_combatant(rec)
        actor = actors_by_id.get(norm.get("source_id"), {})
        name = actor.get("name") or f"source {norm.get('source_id')}"
        if name.lower() in seen:
            continue
        seen.add(name.lower())

        spec = resolve_spec(name, actor.get("subType", ""))
        profile = get_profile(spec) if spec else None
        if profile is None:
            roster.skipped.append((name, f"no profile for {spec}" if spec else "unregistered"))
            continue
        norm["empty_sockets"] = _count_empty_sockets(norm.get("gear", []))
        roster.reports.append(audit_combatant(
            name, spec, profile, norm, report_code=report_code, fight_ids=[fight["id"]]
        ))

    roster.reports.sort(key=lambda r: r.character.lower())
    roster.skipped.sort()
    if not roster.reports and not roster.warnings:
        roster.warnings.append(
            "No registered raiders with an audit profile were found in this report."
        )
    return roster
