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

from core.audit import gemdata
from core.audit.checks import AuditReport, CheckResult, RosterAudit, Section, Verdict
from core.audit.normalize import normalize_combatant
from core.audit.profiles import SpecProfile, get_profile

# Class name (WCL actor subType) → a representative raiding spec, used when the
# log gives us the class but no usable specID. The Preparation checks
# (enchants/gems/consumes) are role-driven, so the exact DPS spec within a class
# rarely changes the prep verdict — this just needs to land on the right profile.
_CLASS_DEFAULT_SPEC: dict[str, str] = {
    "Warrior": "fury_warrior",
    "Paladin": "ret_paladin",
    "Hunter":  "bm_hunter",
    "Rogue":   "combat_rogue",
    "Priest":  "shadow_priest",
    "Shaman":  "ele_shaman",
    "Mage":    "fire_mage",
    "Warlock": "destro_warlock",
    "Druid":   "balance_druid",
}


def _spec_from_log(spec_id, wow_class: str) -> str | None:
    """Derive a canonical spec key from the log's specID, then class default.
    Returns None if neither is usable (caller then tries the registry)."""
    from core.gear_cache import WCL_SPEC_MAP
    if spec_id is not None:
        key = WCL_SPEC_MAP.get(int(spec_id)) if str(spec_id).lstrip("-").isdigit() else None
        if key:
            return key
    return _CLASS_DEFAULT_SPEC.get((wow_class or "").strip())

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
               empty_sockets: int | None = None) -> CheckResult:
    """
    gems: list of {quality, ...} dicts. Flags empty sockets and gems below the
    profile's min quality (green/"uncommon"). empty_sockets is computed against
    the item DB's socket counts (None when unavailable → simply not checked).
    Meta gems are handled separately by check_meta.
    """
    if not gems and empty_sockets is None:
        return CheckResult("gems", "Gems", Verdict.UNKNOWN, "no gem/socket data in log")

    order = {"poor": 0, "common": 1, "uncommon": 2, "rare": 3, "epic": 4, "legendary": 5}
    floor = order.get(profile.min_gem_quality, 3)
    # the meta gem isn't graded on the rare/epic ladder here — that's check_meta
    scored = [g for g in gems if (g.get("color") or "") != "Meta"]
    below = [g for g in scored if order.get(str(g.get("quality", "")).lower(), 99) < floor]
    total = len(scored)

    verdict = Verdict.PASS
    issues: list[str] = []
    if empty_sockets:
        issues.append(f"{empty_sockets} empty socket{'s' if empty_sockets != 1 else ''}")
        verdict = _worst(verdict, Verdict.WARN if empty_sockets <= 2 else Verdict.FAIL)
    if below:
        issues.append(f"{len(below)}/{total} gems below {profile.min_gem_quality} quality")
        verdict = _worst(verdict, Verdict.WARN if len(below) <= 2 else Verdict.FAIL)

    if issues:
        summ = "; ".join(issues)
    elif total:
        summ = f"all {total} gems {profile.min_gem_quality}+ quality, sockets filled"
    else:
        summ = "sockets filled" if empty_sockets == 0 else "no gems socketed"
    return CheckResult("gems", "Gems", verdict, summ,
                       evidence={"below": len(below), "total": total,
                                 "empty_sockets": empty_sockets})


def check_meta(data: dict, profile: SpecProfile) -> CheckResult | None:
    """
    Meta gem: present? correct meta? and — critically — ACTIVE (its color
    requirement met)? Inputs come from the normalized combatant `data`:
      meta_socket : bool  — does any equipped item have a Meta socket?
      meta_id     : int   — the socketed meta gem id (None if none)
      gems        : [{color}] — for counting colors toward the requirement

    Returns None when the player has no meta socket at all (nothing to judge).
    A missing meta gem in a meta socket → WARN. An inactive meta (requirement
    unmet, and the requirement is verified) → FAIL. Unverified requirement →
    PASS with a note (we never false-flag).
    """
    if not data.get("meta_socket"):
        return None

    meta_id = data.get("meta_id")
    if not meta_id:
        want = f" — want {profile.meta_gem}" if profile.meta_gem else ""
        return CheckResult("meta", "Meta gem", Verdict.WARN,
                           f"meta socket empty — no meta gem socketed{want}")

    req = gemdata.meta_requirement(meta_id)
    name = (req or {}).get("name") or "meta gem"

    # Count colors across non-meta gems; compound gems count toward each component.
    counts: dict[str, int] = {}
    for g in data.get("gems", []):
        for comp in gemdata.COLOR_COMPONENTS.get(g.get("color") or "", set()):
            counts[comp] = counts.get(comp, 0) + 1

    if not req or not req.get("require"):
        return CheckResult("meta", "Meta gem", Verdict.PASS,
                           f"{name} socketed (activation requirement not on file)")

    unmet = {c: n for c, n in req["require"].items() if counts.get(c, 0) < n}
    if not unmet:
        return CheckResult("meta", "Meta gem", Verdict.PASS, f"{name} active")
    need = ", ".join(f"{n} {c}" for c, n in req["require"].items())
    have = ", ".join(f"{counts.get(c, 0)} {c}" for c in req["require"]) or "none"
    if not req.get("verified"):
        return CheckResult("meta", "Meta gem", Verdict.PASS,
                           f"{name} socketed (needs {need}; requirement unverified)")
    return CheckResult(
        "meta", "Meta gem", Verdict.FAIL,
        f"{name} is INACTIVE — needs {need}, you have {have}",
        detail="An inactive meta gem gives no bonus at all. Add blue/purple/green "
               "gems (which count toward the Blue requirement) to switch it on.",
        evidence={"meta_id": meta_id, "require": req["require"], "counts": counts})


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

    # One consumable per line (sub-bulleted under the Consumes header) instead of
    # a run-on "Food: ✅; Oil: ❌; Potions: ❌" string that's hard to scan.
    summary = "\n" + "\n".join(f"   • {ln}" for ln in lines) if lines else "none expected"
    return CheckResult("consumes", "Consumes", worst, summary,
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

def check_end_activity(cast_times: list[float], fight_window: tuple[float, float],
                       profile: SpecProfile) -> CheckResult | None:
    """
    Healer-only signal. cast_times: ms timestamps of the player's casts;
    fight_window: (start_ms, end_ms), both report-relative.

    Flags a long trailing silence (no casts well before the kill) as INDICATIVE
    of going OOM. WARN, never FAIL: a quiet stretch can also be a legitimate
    end-of-fight lull while the boss dies. Returns None when the profile opts out
    (DPS/tanks), so it never penalises throughput.
    """
    warn_sec = getattr(profile, "end_silence_warn_sec", 0.0)
    if not warn_sec:
        return None
    start, end = fight_window
    dur = (end - start) / 1000.0
    if dur <= 0:
        return CheckResult("end_activity", "End-of-fight activity", Verdict.UNKNOWN,
                           "no fight timing")
    if not cast_times:
        return CheckResult("end_activity", "End-of-fight activity", Verdict.UNKNOWN,
                           "no cast data")
    trailing = max(0.0, (end - max(cast_times)) / 1000.0)
    # Flag only when the silence is both absolutely long and a real share of the
    # fight, so a short natural lull at the kill doesn't trip it.
    if trailing >= warn_sec and trailing >= 0.12 * dur:
        return CheckResult(
            "end_activity", "End-of-fight activity", Verdict.WARN,
            f"no casts for the final {trailing:.0f}s of a {dur:.0f}s fight",
            detail=("A long silence before the kill often means running low on mana. "
                    "It can also be a normal lull as the boss dies — worth a glance at "
                    "mana management/regen rather than a throughput judgement."),
            evidence={"trailing_silence_sec": round(trailing, 1), "fight_sec": round(dur, 1)})
    return CheckResult("end_activity", "End-of-fight activity", Verdict.PASS,
                       f"casting through to ~{trailing:.0f}s before the end")


_POTION_RE = re.compile(r"potion", re.I)


def _tally_casts(casts: list[dict], abilities: list[dict]) -> dict:
    """
    From cast events + the report ability table, return
    {source_id: {"potions": int, "cast_times": [ms]}}.

    Potions are counted as completed casts whose ability name contains "Potion"
    (Super Mana / Haste / Insane Strength / Destruction / Ironshield / healing…).
    """
    name_by_id = {a.get("gameID"): (a.get("name") or "") for a in abilities}
    out: dict = {}
    for e in casts:
        if e.get("type") != "cast":
            continue
        rec = out.setdefault(e.get("sourceID"), {"potions": 0, "cast_times": []})
        ts = e.get("timestamp")
        if ts is not None:
            rec["cast_times"].append(ts)
        if _POTION_RE.search(name_by_id.get(e.get("abilityGameID"), "")):
            rec["potions"] += 1
    return out


def _rotation_execution(spec: str, casts, abilities, fight_name: str = "") -> list:
    """
    Bridge the rotation engine into the audit's Execution section. Runs
    rotation_handler.analyze for any spec that has a rotation profile and returns
    a list of CheckResults (downranks → FAIL, off-rotation → WARN, baseline CPM →
    INFO, else a PASS). Empty list when no profile or no cast data.
    """
    if not casts:
        return []
    from core import rotation_handler as RH
    prof = RH.load_profile(spec)
    if not prof:
        return []
    baseline = RH.load_baseline(spec, fight_name) if fight_name else None
    a = RH.analyze(casts, abilities or [], prof,
                   max_rank_ids=RH.verified_max_ranks(prof), baseline=baseline)

    out = []
    if a.downranks:
        out.append(CheckResult("rotation_ranks", "Spell ranks", Verdict.FAIL,
                               a.downranks[0],
                               detail="; ".join(a.downranks[1:])))
    if a.off_rotation:
        out.append(CheckResult("rotation_offspec", "Off-rotation", Verdict.WARN,
                               "; ".join(a.off_rotation)))
    if not a.downranks and not a.off_rotation:
        out.append(CheckResult("rotation", "Rotation", Verdict.PASS,
                               "no downranked nukes or off-rotation spells"))
    # Surface the baseline cast-rate comparison (if a baseline was available).
    for adv in a.advisories:
        if adv.startswith("**Cast-rate vs top"):
            out.append(CheckResult("cpm", "Cast rate", Verdict.INFO,
                                   adv.split("\n", 1)[0].replace("**", "")))
    return out


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
    preparation.add(check_consumes(data.get("auras", []), profile,
                                   potion_count=data.get("potion_count")))
    preparation.add(check_enchants(data.get("gear", []), profile))
    preparation.add(check_gems(data.get("gems", []), profile,
                               empty_sockets=data.get("empty_sockets")))
    meta = check_meta(data, profile)
    if meta is not None:
        preparation.add(meta)

    sections = [baseline, preparation]

    # Execution: rotation analysis (reuses the rotation engine) for any spec with
    # a rotation profile, plus the healer end-of-fight silence check.
    execution = Section("Execution")
    execution.checks.extend(_rotation_execution(
        spec, data.get("casts"), data.get("abilities"), data.get("fight_name", "")))

    cast_times = data.get("cast_times")
    fight_window = data.get("fight_window")
    if profile.end_silence_warn_sec and cast_times is not None and fight_window:
        end_act = check_end_activity(cast_times, fight_window, profile)
        if end_act is not None:
            execution.add(end_act)

    if execution.checks:
        sections.append(execution)

    report.sections = sections
    return report


# ---------------------------------------------------------------------------
# WCL gathering (the only network in this module)
# ---------------------------------------------------------------------------

def _socket_info(gear: list[dict]) -> dict:
    """
    Using the item DB's per-item socket colors, return
        {"empty_sockets": int | None, "meta_socket": bool}
    `empty_sockets` counts ungemmed non-meta sockets; `meta_socket` is True if any
    equipped item has a Meta socket (so a missing meta gem can be flagged).
    empty_sockets is None when the item DB isn't available (then it's not scored).
    """
    import json as _json
    import os as _os
    import sqlite3 as _sqlite3

    import config

    if not _os.path.exists(config.ITEM_DB_PATH):
        return {"empty_sockets": None, "meta_socket": False}
    try:
        conn = _sqlite3.connect(config.ITEM_DB_PATH)
    except _sqlite3.Error:
        return {"empty_sockets": None, "meta_socket": False}
    empty = 0
    meta_socket = False
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
            if any(str(c).lower() == "meta" for c in colors):
                meta_socket = True
            nonmeta_sockets = sum(1 for c in colors if str(c).lower() != "meta")
            socketed = sum(1 for gm in (g.get("gems") or [])
                           if not gemdata.is_meta(gm.get("item_id") or 0))
            empty += max(0, nonmeta_sockets - socketed)
    finally:
        conn.close()
    return {"empty_sockets": empty, "meta_socket": meta_socket}


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
    norm.update(_socket_info(norm.get("gear", [])))

    # One cast fetch powers potion tracking (all specs) and the healer
    # end-of-fight silence check. Best-effort: never break the audit over it.
    try:
        from core import wcl_client
        raw_casts = wcl_client.get_casts(report_code, fight["id"], target_id)
        abilities = wcl_client.get_abilities(report_code)
        tally = _tally_casts(raw_casts, abilities).get(
            target_id, {"potions": 0, "cast_times": []})
        norm["potion_count"] = tally["potions"]
        norm["casts"] = raw_casts            # for the Execution rotation check
        norm["abilities"] = abilities
        norm["fight_name"] = fight.get("name", "")
        if profile.end_silence_warn_sec:
            norm["cast_times"] = tally["cast_times"]
            norm["fight_window"] = (fight.get("startTime", 0), fight.get("endTime", 0))
    except Exception as exc:
        log.warning("cast/potion fetch failed for %s: %s", character, exc)

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

    # One fight-wide cast fetch powers potion tracking (+ healer end-activity) for
    # the whole roster, instead of N per-player queries. None = fetch failed →
    # potions show ❔ rather than a false ❌.
    cast_tally = None
    all_casts: list = []
    abilities: list = []
    try:
        from core import wcl_client
        all_casts = wcl_client.get_casts(report_code, fight["id"])
        abilities = wcl_client.get_abilities(report_code)
        cast_tally = _tally_casts(all_casts, abilities)
    except Exception as exc:
        log.warning("roster cast/potion fetch failed: %s", exc)
    # Group raw casts per source for the rotation Execution check.
    casts_by_source: dict = {}
    for c in all_casts:
        casts_by_source.setdefault(c.get("sourceID"), []).append(c)

    seen: set[str] = set()
    for rec in combatants:
        norm = normalize_combatant(rec)
        actor = actors_by_id.get(norm.get("source_id"), {})
        name = actor.get("name") or f"source {norm.get('source_id')}"
        if name.lower() in seen:
            continue
        seen.add(name.lower())

        # Prefer the spec the LOG reports (specID from CombatantInfo), then the
        # class default, and only fall back to the guild registry. The log is
        # ground truth — this audits the whole raid without prior registration
        # AND fixes stale/wrong registry entries (e.g. a warrior mis-saved as a
        # druid). resolve_spec (registry) is the last resort, not the first.
        spec = _spec_from_log(norm.get("spec_id"), actor.get("subType", "")) \
            or resolve_spec(name, actor.get("subType", ""))
        profile = get_profile(spec) if spec else None
        if profile is None:
            why = f"no audit profile for {spec}" if spec else "couldn't determine spec from log"
            roster.skipped.append((name, why))
            continue
        norm.update(_socket_info(norm.get("gear", [])))
        if cast_tally is not None:
            t = cast_tally.get(norm.get("source_id"), {"potions": 0, "cast_times": []})
            norm["potion_count"] = t["potions"]
            norm["casts"] = casts_by_source.get(norm.get("source_id"), [])
            norm["abilities"] = abilities
            norm["fight_name"] = fight.get("name", "")
            if profile.end_silence_warn_sec:
                norm["cast_times"] = t["cast_times"]
                norm["fight_window"] = (fight.get("startTime", 0), fight.get("endTime", 0))
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
