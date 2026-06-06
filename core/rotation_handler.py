"""
BrnzyBot rotation check — deterministic per-cast anomaly detection.

Flow
────
  1. Resolve a log/pull for the character:
       - explicit:  a WCL report code / URL (+ optional fight) the user passes
       - auto:      the character's most recent parse in their recent reports
  2. Pull the actor's cast events + the report's ability table from WCL.
  3. Compare casts against the spec's expected rotation profile
     (data/rotations/{spec}.json) and flag anomalies.
  4. Return a Discord-ready string. With ENABLE_LLM, an optional coaching
     paragraph is appended; the deterministic report is always the product.

Anomaly model (intentionally conservative — anomaly-focused, low false positives):
  - Downrank: each WoW spell rank is a distinct game ID. Each spec profile
    carries the verified TBC max-rank ID per watched spell (ranks_verified +
    max_rank_ids); we flag the player's casts whose game ID is BELOW that max.
    This catches the "button bound to an old rank, wrong every cast" case as
    well as occasional misclicks. We deliberately do NOT infer the max rank
    from the log environment — WCL report metadata can carry non-TBC (e.g.
    WotLK) spell IDs, and trusting them produced false positives. Spells with no
    verified max rank are simply not rank-checked (no guessing, no false alarms).
  - Off-rotation: spells a spec should not be casting on a DPS parse (heals,
    wrong-school nukes, wrong-build fillers), past a per-spell cast threshold.
  - Breakpoint/advisory: informational notes (e.g. Chain Lightning weaving).

Handlers return strings; the cog owns all Discord I/O.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter
from dataclasses import dataclass, field

import config
from core import entitlements
from core import wcl_client as wcl

try:
    from core.classifier import SPEC_ALIASES, VALID_SPECS
except Exception:  # pragma: no cover - classifier should always import
    SPEC_ALIASES, VALID_SPECS = {}, frozenset()

log = logging.getLogger(__name__)

ROTATIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "rotations")

# Only cast events count as a "cast"; begincast is the start of a cast-time spell.
_CAST_TYPE = "cast"

# LiteLLM coaching (optional, gated on ENABLE_LLM)
_LLM_MODEL   = config.MODEL_ESCALATION
_LLM_TIMEOUT = 60


# ---------------------------------------------------------------------------
# Profile loading
# ---------------------------------------------------------------------------
def _profile_path(spec: str) -> str:
    return os.path.join(ROTATIONS_DIR, f"{spec}.json")


def covered_specs() -> list[str]:
    """Spec keys we have a rotation profile for, sorted."""
    try:
        return sorted(
            f[:-5] for f in os.listdir(ROTATIONS_DIR) if f.endswith(".json")
        )
    except FileNotFoundError:
        return []


def _resolve_spec_key(spec: str) -> str:
    """Map a raw spec string to a canonical key (best effort)."""
    s = (spec or "").strip().lower().replace(" ", "_")
    if s in VALID_SPECS:
        return s
    return SPEC_ALIASES.get(s, s)


def load_profile(spec: str) -> dict | None:
    path = _profile_path(_resolve_spec_key(spec))
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _derive_spec_from_log(code: str, fight_id: int, actor_id: int) -> str | None:
    """Read the player's spec from the analyzed pull's CombatantInfo (specID)."""
    try:
        events = wcl.get_combatant_info(code, fight_id)
    except RuntimeError:
        return None
    rec = next((e for e in events if e.get("sourceID") == actor_id), None)
    if rec is None and events:
        rec = events[-1]
    if not rec:
        return None
    from core.gear_cache import WCL_SPEC_MAP  # lazy: keep import-light for CI checks
    return WCL_SPEC_MAP.get(rec.get("specID"))


def verified_max_ranks(profile: dict) -> dict[str, int]:
    """The profile's authoritative {spell: max_rank_game_id}, or {} if unverified."""
    if not profile.get("ranks_verified"):
        return {}
    return {k: int(v) for k, v in (profile.get("max_rank_ids") or {}).items()}


# ---------------------------------------------------------------------------
# Report-reference parsing (explicit override)
# ---------------------------------------------------------------------------
_CODE_RE  = re.compile(r"/reports/([A-Za-z0-9]+)")
_FIGHT_RE = re.compile(r"fight=(\d+)")
_BARE_RE  = re.compile(r"^[A-Za-z0-9]{16,}$")


def parse_report_ref(ref: str) -> tuple[str | None, int | None]:
    """
    Parse a WCL report code or URL into (code, fight_id|None).
    Accepts a bare code, or a full URL like
    https://classic.warcraftlogs.com/reports/aBc123#fight=5
    """
    if not ref:
        return None, None
    ref = ref.strip()
    fight = None
    m = _FIGHT_RE.search(ref)
    if m:
        fight = int(m.group(1))
    m = _CODE_RE.search(ref)
    if m:
        return m.group(1), fight
    # bare token (strip any trailing fragment)
    token = ref.split("#")[0].split("?")[0].strip("/")
    token = token.split("/")[-1]
    if _BARE_RE.match(token):
        return token, fight
    return None, fight


# ---------------------------------------------------------------------------
# Log resolution
# ---------------------------------------------------------------------------
def _find_actor_id(actors: list[dict], name: str) -> int | None:
    for actor in actors:
        if (actor.get("name") or "").lower() == name.lower():
            return actor.get("id")
    return None


def _best_fight_for_actor(fights: list[dict], actor_id: int) -> dict | None:
    """Pick the longest fight the actor participated in (best rotation sample)."""
    present = [
        f for f in fights
        if actor_id in (f.get("friendlyPlayers") or [])
    ]
    if not present:
        return None
    kills = [f for f in present if f.get("kill")]
    pool = kills or present
    return max(pool, key=lambda f: (f.get("endTime", 0) - f.get("startTime", 0)))


@dataclass
class _ResolvedLog:
    code:        str
    fight_id:    int
    actor_id:    int
    fight_name:  str
    duration_s:  float


def _resolve_log(
    character: str, realm: str, region: str,
    report_ref: str | None, fight_override: int | None,
) -> _ResolvedLog | str:
    """Return a _ResolvedLog or a user-facing error string."""
    # --- explicit report override ---
    if report_ref:
        code, parsed_fight = parse_report_ref(report_ref)
        if not code:
            return ("That doesn't look like a Warcraft Logs report link or code. "
                    "Paste a report URL or its code, e.g. `aBcD1234EfGh5678`.")
        fight_id = fight_override or parsed_fight
        actors = wcl.get_master_actors(code)
        actor_id = _find_actor_id(actors, character)
        if actor_id is None:
            return f"**{character}** isn't in report `{code}` (checked player names)."
        fights = wcl.get_fights(code)
        if fight_id is not None:
            fight = next((f for f in fights if f.get("id") == fight_id), None)
            if fight is None:
                return f"Fight {fight_id} not found in report `{code}`."
        else:
            fight = _best_fight_for_actor(fights, actor_id)
            if fight is None:
                return f"**{character}** has no fights in report `{code}`."
        return _ResolvedLog(
            code=code, fight_id=fight["id"], actor_id=actor_id,
            fight_name=fight.get("name", f"Fight {fight['id']}"),
            duration_s=max(0.0, (fight.get("endTime", 0) - fight.get("startTime", 0)) / 1000.0),
        )

    # --- auto: walk the character's recent reports ---
    reports = wcl.get_character_recent_reports(character, realm, region, limit=3)
    if not reports:
        return (f"Couldn't find any recent Warcraft Logs reports for "
                f"**{character}**-{realm}. Paste a report link to check a specific pull.")
    for rep in reports:
        code = rep.get("code")
        if not code:
            continue
        actors = wcl.get_master_actors(code)
        actor_id = _find_actor_id(actors, character)
        if actor_id is None:
            continue
        fights = wcl.get_fights(code)
        fight = _best_fight_for_actor(fights, actor_id)
        if fight is None:
            continue
        return _ResolvedLog(
            code=code, fight_id=fight["id"], actor_id=actor_id,
            fight_name=fight.get("name", f"Fight {fight['id']}"),
            duration_s=max(0.0, (fight.get("endTime", 0) - fight.get("startTime", 0)) / 1000.0),
        )
    return (f"Found reports for **{character}** but couldn't locate a pull with "
            "their casts. Paste a specific report link to check a pull.")


# ---------------------------------------------------------------------------
# Anomaly engine (pure — easy to unit-test with synthetic data)
# ---------------------------------------------------------------------------
@dataclass
class Analysis:
    total_casts:    int
    breakdown:      list[tuple[str, int]]          # (spell_name, count) desc
    downranks:      list[str] = field(default_factory=list)
    off_rotation:   list[str] = field(default_factory=list)
    advisories:     list[str] = field(default_factory=list)
    unknown_casts:  int = 0


def analyze(
    casts: list[dict], abilities: list[dict], profile: dict,
    max_rank_ids: dict[str, int] | None = None,
) -> Analysis:
    """
    Compare a player's casts against a spec rotation profile.

    `max_rank_ids` is the authoritative {spell: max_rank_game_id} map (from the
    profile's verified table). A watched spell is rank-checked only if it has an
    entry here; casts with a game ID below the verified max are flagged. We never
    infer the max rank from the report (WCL metadata can carry non-TBC IDs).
    """
    max_rank_ids = max_rank_ids or {}
    name_by_id = {a.get("gameID"): a.get("name") for a in abilities}

    # Aggregate the target player's completed casts by spell name + game ID.
    by_name: dict[str, dict] = {}
    unknown = 0
    for ev in casts:
        if ev.get("type") != _CAST_TYPE:
            continue
        gid = ev.get("abilityGameID")
        nm = name_by_id.get(gid)
        if not nm:
            unknown += 1
            nm = f"Spell #{gid}"
        rec = by_name.setdefault(nm, {"total": 0, "ids": Counter()})
        rec["total"] += 1
        rec["ids"][gid] += 1

    total = sum(r["total"] for r in by_name.values())
    breakdown = sorted(
        ((nm, r["total"]) for nm, r in by_name.items()),
        key=lambda kv: kv[1], reverse=True,
    )

    downranks: list[str] = []
    for spell in profile.get("downrank_watch", []):
        rec = by_name.get(spell)
        if not rec:
            continue
        ref = max_rank_ids.get(spell)
        if ref is None:
            continue  # no verified max rank for this spell — don't guess
        low = sum(c for gid, c in rec["ids"].items() if gid < ref)
        if low <= 0:
            continue
        if low == rec["total"]:
            downranks.append(
                f"**{spell}** — all {rec['total']} casts were below max rank. Every cast "
                "landing on one lower rank usually means a button bound to an old rank "
                "(common on freshly-70 characters) rather than an in-the-moment choice — "
                "rebinding to max rank is a free upgrade."
            )
        else:
            downranks.append(
                f"**{spell}** — {low} of {rec['total']} casts were below max rank. "
                "Could be a stray old-rank button/macro, or intentional (movement, mana). Worth a glance."
            )

    off: list[str] = []
    for nm, cfg in (profile.get("off_rotation") or {}).items():
        rec = by_name.get(nm)
        if not rec:
            continue
        if rec["total"] >= int(cfg.get("min_casts", 1)):
            off.append(f"**{nm}** ×{rec['total']} — {cfg.get('note', 'off-rotation cast')}.")

    advisories: list[str] = []
    bp = profile.get("breakpoint")
    if bp and bp.get("spells"):
        counts = [(s, by_name.get(s, {}).get("total", 0)) for s in bp["spells"]]
        observed = ", ".join(f"{s} ×{c}" for s, c in counts)
        advisories.append(f"{bp.get('note', '')} (observed: {observed})")
    if profile.get("advisory"):
        advisories.append(profile["advisory"])

    return Analysis(
        total_casts=total, breakdown=breakdown, downranks=downranks,
        off_rotation=off, advisories=advisories, unknown_casts=unknown,
    )


# ---------------------------------------------------------------------------
# Optional LLM coaching (gated on ENABLE_LLM)
# ---------------------------------------------------------------------------
def _coach(profile: dict, analysis: Analysis, character: str) -> str | None:
    """Short coaching paragraph via LiteLLM→Claude. Returns None on any failure."""
    findings = analysis.downranks + analysis.off_rotation
    if not findings:
        return None
    top = ", ".join(f"{nm} ×{c}" for nm, c in analysis.breakdown[:8])
    sys = (
        "You are BrnzyBot, a warm and encouraging TBC Classic raid coach talking to a "
        "guildmate about their parse. Write 2-4 sentences of kind, constructive feedback.\n"
        "Principles:\n"
        "- Lead with something genuine and positive about what they did well.\n"
        "- Frame issues as gentle, optional suggestions ('you might try…', 'one thing "
        "worth a look…'), never criticism or commands.\n"
        "- Stay humble: you only see a cast list, not the fight. Explicitly allow that "
        "movement, target swaps, mana, or assignments may explain what you see.\n"
        "- Where it helps, ground a suggestion in the math — spell coefficients, "
        "cast-time vs damage, mana efficiency, DoT uptime value — so the 'why' is clear.\n"
        "- No preamble, no headers, no bullet lists. Just a friendly note."
    )
    user = (
        f"Spec: {profile.get('display')}. Expected play: {profile.get('summary')}\n"
        f"Their top casts: {top}\n"
        f"Things I noticed (treat as possibilities, not certainties): {'; '.join(findings)}"
    )
    from core import llm
    messages = [{"role": "system", "content": sys}, {"role": "user", "content": user}]
    try:
        return llm.chat(_LLM_MODEL, messages, temperature=0.3,
                        max_tokens=300, timeout=_LLM_TIMEOUT).strip()
    except RuntimeError as e:
        log.warning("rotation coach LLM call failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------
def _format(profile: dict, rlog: _ResolvedLog, analysis: Analysis,
            character: str) -> str:
    cpm = (analysis.total_casts / (rlog.duration_s / 60.0)) if rlog.duration_s else 0.0
    lines = [
        f"🌀 **Rotation Check — {character}** ({profile.get('display', profile.get('spec'))})",
        f"Log `{rlog.code}` · {rlog.fight_name} · {rlog.duration_s:.0f}s · "
        f"{analysis.total_casts} casts ({cpm:.0f}/min)",
        f"_Expected:_ {profile.get('summary', '')}",
        "",
        "**Cast breakdown:**",
    ]
    for nm, count in analysis.breakdown[:12]:
        lines.append(f"  • {nm} ×{count}")
    if len(analysis.breakdown) > 12:
        lines.append(f"  • …and {len(analysis.breakdown) - 12} more")

    issues = analysis.downranks + analysis.off_rotation
    if issues:
        lines += ["", "⚠️ **Anomalies:**"]
        lines += [f"  • {x}" for x in issues]
    else:
        lines += ["", "✅ No obvious rotation anomalies (no downranked nukes or off-rotation spells detected)."]

    if analysis.advisories:
        lines += ["", "ℹ️ **Notes:**"]
        lines += [f"  • {x}" for x in analysis.advisories]

    lines += ["", "_Anomaly-focused check: flags accidental lower-rank casts and off-rotation "
              "spells. It does not grade overall DPS or uptime._"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def handle_rotation_check(
    character: str,
    spec: str | None = None,
    realm: str = "",
    region: str = "us",
    guild_id: str = "global",
    report: str | None = None,
    fight: int | None = None,
) -> str:
    """
    Deterministic rotation check. Returns Discord-ready text (never posts).

    Works for unregistered characters: the log is resolved first, then the spec
    is taken from a usable provided/registered `spec` or derived from the actual
    pull. `report` is an optional WCL code/URL override; `fight` an optional id.
    """
    # 1. Resolve the log first — this works for any character with logs, so an
    #    unregistered name still gets a real check (or a clear "no logs" message).
    try:
        resolved = _resolve_log(character, realm, region, report, fight)
    except RuntimeError as e:
        return f"Warcraft Logs is unreachable right now ({e}). Try again in a moment."
    if isinstance(resolved, str):
        return resolved

    # 2. Resolve the spec: prefer a usable provided/registered spec, otherwise
    #    derive it from the pull we're about to analyze (more accurate anyway).
    spec_key = _resolve_spec_key(spec) if spec else None
    profile = load_profile(spec_key) if spec_key else None
    if profile is None:
        derived = _derive_spec_from_log(resolved.code, resolved.fight_id, resolved.actor_id)
        if derived:
            profile = load_profile(derived)
    if profile is None:
        covered = ", ".join(covered_specs()) or "(none)"
        who = f"**{spec}**" if spec else f"**{character}**'s spec"
        return (
            f"Rotation check doesn't cover {who} yet. "
            f"Currently supported (caster DPS): {covered}."
        )

    try:
        casts = wcl.get_casts(resolved.code, resolved.fight_id, resolved.actor_id)
        abilities = wcl.get_abilities(resolved.code)
    except RuntimeError as e:
        return f"Couldn't pull cast data from Warcraft Logs ({e}). Try again in a moment."

    if not casts:
        return (f"No casts found for **{character}** in {resolved.fight_name} "
                f"(`{resolved.code}`). They may not have cast anything in that pull.")

    analysis = analyze(casts, abilities, profile,
                       max_rank_ids=verified_max_ranks(profile))
    out = _format(profile, resolved, analysis, character)

    if entitlements.llm_enabled(guild_id):
        coached = _coach(profile, analysis, character)
        if coached:
            out += f"\n\n🤖 **Coach:** {coached}"
            entitlements.note_llm_call(guild_id)
    return out
