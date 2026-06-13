"""
phase.py - realm + date driven phase resolution.

Phase progression in TBC Classic is a realm-wide calendar fact set by Blizzard,
not a per-guild choice. This module derives the current phase from
`realm + today's date` using `data/phase_schedule.json`, so guild admins never
have to set it (an explicit override remains available for private servers / PTR).

Two distinct axes, deliberately kept separate (see docs/PHASE_READINESS.md s1):
  - calendar_phase    - what the realm calls "the current phase" (gear tier
                        markers, phase labels key off this).
  - content_phase_max - the WowSims item-DB ceiling the optimizer filters on
                        (`phase <= ?`). On the Anniversary calendar these diverge:
                        calendar P3 folds in Zul'Aman, whose gear is tagged item
                        content-phase 4 - so P3's content_phase_max is 4, not 3.
                        This is the "ZA ceiling" fix.

`resolve_phase` never raises: an unknown realm falls back to the `_default`
ruleset, and an all-null calendar yields phase 1.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

log = logging.getLogger(__name__)

_SCHEDULE_PATH = os.environ.get(
    "PHASE_SCHEDULE_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "data", "phase_schedule.json"),
)

# Conservative fallback used only if the schedule file is missing/unreadable.
_FALLBACK_PHASE = {
    "phase": 1, "content_phase_max": 1, "arena_season": 1,
    "raids": ["Karazhan", "Gruul's Lair", "Magtheridon's Lair"],
}


@dataclass
class PhaseInfo:
    calendar_phase: int        # what the realm calls "the current phase"
    content_phase_max: int     # WowSims item-DB ceiling for the optimizer
    raids: list[str] = field(default_factory=list)
    arena_season: int = 1
    ruleset: str = "anniversary"
    source: str = "auto"       # "auto" | "override" | "fallback"


_cache: Optional[dict] = None


def load_schedule(force: bool = False) -> dict:
    """Load and cache data/phase_schedule.json. Returns {} on any failure."""
    global _cache
    if _cache is not None and not force:
        return _cache
    try:
        with open(_SCHEDULE_PATH, encoding="utf-8-sig") as f:
            _cache = json.load(f)
    except (OSError, ValueError) as e:
        log.warning("phase: could not load schedule %s (%s); using fallback",
                    _SCHEDULE_PATH, e)
        _cache = {}
    return _cache


def _ruleset_for(realm: str, schedule: dict) -> tuple[str, dict]:
    """Resolve a realm to (ruleset_name, ruleset_dict). Falls back to _default."""
    realms = schedule.get("realms", {})
    rulesets = schedule.get("rulesets", {})
    name = realms.get((realm or "").lower()) or realms.get("_default") or "anniversary"
    return name, rulesets.get(name, {})


def _phases(ruleset: dict) -> list[dict]:
    return sorted(ruleset.get("phases", []), key=lambda p: p.get("phase", 0))


def max_calendar_phase(realm: str = "_default") -> int:
    """Highest calendar phase the realm's ruleset defines (for bound validation).
    Anniversary = 4. Falls back to 1 if the schedule is unavailable."""
    _name, ruleset = _ruleset_for(realm, load_schedule())
    phases = _phases(ruleset)
    return phases[-1]["phase"] if phases else 1


def _info_from_entry(entry: dict, name: str, source: str) -> PhaseInfo:
    return PhaseInfo(
        calendar_phase=entry.get("phase", 1),
        content_phase_max=entry.get("content_phase_max", entry.get("phase", 1)),
        raids=list(entry.get("raids", [])),
        arena_season=entry.get("arena_season", 1),
        ruleset=name,
        source=source,
    )


def resolve_phase(realm: str = "_default", *, today: Optional[date] = None,
                  override: Optional[int] = None) -> PhaseInfo:
    """Resolve the active phase for a realm.

    Resolution order:
      1. `override` (admin / per-command escape hatch) - clamped to the ruleset's
         valid range, mapped to that calendar phase's entry (so content_phase_max
         stays correct). source="override".
      2. Auto: the highest phase whose `release` is a real date <= today.
         source="auto". If none qualify (all null / future), phase 1.

    Never raises.
    """
    today = today or date.today()
    schedule = load_schedule()
    name, ruleset = _ruleset_for(realm, schedule)
    phases = _phases(ruleset)

    if not phases:
        log.warning("phase: empty ruleset for realm=%r; using fallback", realm)
        return _info_from_entry(_FALLBACK_PHASE, name, "fallback")

    if override is not None:
        lo, hi = phases[0]["phase"], phases[-1]["phase"]
        clamped = max(lo, min(hi, override))
        entry = next((p for p in phases if p.get("phase") == clamped), phases[0])
        info = _info_from_entry(entry, name, "override")
        log.info("phase: realm=%s override=%s -> calendar=%d content_max=%d",
                 realm, override, info.calendar_phase, info.content_phase_max)
        return info

    # Auto: walk dated phases, pick the latest one already released.
    current = phases[0]
    for p in phases:
        rel = p.get("release")
        if not rel:
            continue  # announced-but-undated: previous dated phase holds
        try:
            rel_date = date.fromisoformat(rel)
        except ValueError:
            continue
        if rel_date <= today:
            current = p
    info = _info_from_entry(current, name, "auto")
    log.debug("phase: realm=%s today=%s -> calendar=%d content_max=%d (%s)",
              realm, today, info.calendar_phase, info.content_phase_max, name)
    return info


def resolve_for_guild(guild_id: str, *, override: Optional[int] = None,
                      today: Optional[date] = None) -> PhaseInfo:
    """Guild-facing resolution: read the guild's realm (server_slug) and stored
    phase override from the DB, honoring a per-command `override` if given.

    DB access is best-effort - any failure falls back to the default realm with
    no override (pure auto), so this never breaks a command.
    """
    realm = None
    stored_override = None
    try:
        import config
        from db.server_config import get_guild_config, get_phase_override
        cfg = get_guild_config(guild_id) or {}
        realm = cfg.get("server_slug") or getattr(config, "DEFAULT_REALM", "_default")
        if override is None:
            stored_override = get_phase_override(guild_id)
    except Exception as e:  # pragma: no cover - defensive
        log.warning("phase: guild lookup failed for %s (%s); auto on default realm",
                    guild_id, e)
        realm = realm or "_default"

    effective = override if override is not None else stored_override
    return resolve_phase(realm or "_default", today=today, override=effective)
