"""
Raid Audit Matrix — whole-report consumable/prep grid (players × boss kills).

Stage 1: the data layer. `gather_raid_matrix(code)` walks a WCL report and returns
a structured, render-agnostic snapshot: every kill fight, every raider, and per
(player, fight) their consumable auras + potion count + the spec they ran that
fight. Pure aside from the WCL fetch — the grading and rendering live elsewhere
so each stage is testable on its own.

Creature-type helpers (for Demonslaying-on-a-non-demon grading) and the wing
chunking (4-6 bosses per table) load from data/boss_types.json.

See docs/RAID_AUDIT_MATRIX.md for the full design.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
_BOSS_TYPES_PATH = os.path.join(_DATA, "boss_types.json")

_boss_types: dict | None = None


def _load_boss_types() -> dict:
    global _boss_types
    if _boss_types is None:
        try:
            with open(_BOSS_TYPES_PATH, encoding="utf-8-sig") as f:
                _boss_types = json.load(f)
        except (FileNotFoundError, ValueError) as e:
            log.warning("boss_types unavailable: %s", e)
            _boss_types = {}
    return _boss_types


def creature_type(boss_name: str) -> str | None:
    """Return 'Demon' / 'Undead' for a boss whose type gates a consumable, else
    None (no type-gated consumable applies). Matched by lowercased substring."""
    t = _load_boss_types()
    n = (boss_name or "").lower()
    if any(d in n for d in t.get("demon_bosses", [])):
        return "Demon"
    if any(u in n for u in t.get("undead_bosses", [])):
        return "Undead"
    return None


def chunk_fights(zone_name: str, fight_names: list[str]) -> list[list[int]]:
    """
    Partition fight indices into comfortable matrix tables. Prefers the instance's
    known wings (data/boss_types.json); falls back to fixed 6-boss chunks when the
    zone isn't mapped. Returns lists of indices into `fight_names`.
    """
    t = _load_boss_types()
    wings = (t.get("wings") or {}).get(zone_name)
    if wings:
        chunks: list[list[int]] = []
        used: set[int] = set()
        for wing in wings:
            idxs = []
            for i, fname in enumerate(fight_names):
                if i in used:
                    continue
                fl = fname.lower()
                if any(b.lower() in fl or fl in b.lower() for b in wing):
                    idxs.append(i)
                    used.add(i)
            if idxs:
                chunks.append(idxs)
        # any kills not matched to a wing (odd names) → their own trailing chunk
        leftover = [i for i in range(len(fight_names)) if i not in used]
        for i in range(0, len(leftover), 6):
            chunks.append(leftover[i:i + 6])
        if chunks:
            return chunks
    # Unknown zone: fixed 6-wide chunks.
    return [list(range(i, min(i + 6, len(fight_names))))
            for i in range(0, len(fight_names), 6)]


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass
class Cell:
    """One (player, fight) consumable snapshot — pre-grading."""
    auras: list[str] = field(default_factory=list)   # consumable buff names at pull
    potions: int = 0                                  # potion casts in the fight
    spec: str | None = None                           # spec run THIS fight
    present: bool = False                             # did the player appear in this fight


@dataclass
class RaidMatrix:
    report_code: str
    zone: str = ""
    start_time: int | None = None                     # report start (ms) for the header date
    fights: list[dict] = field(default_factory=list)  # [{id, name, kill}]
    players: list[dict] = field(default_factory=list) # [{name, class, usual_spec}]
    # cells[player_name][fight_id] = Cell
    cells: dict = field(default_factory=dict)
    # roster-wide gear (gems/enchants don't change per pull): name -> normalized combatant
    gear: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Gather
# ---------------------------------------------------------------------------

_CONSUMABLE_HINTS = ("flask", "elixir", "oil", "well fed", "food",
                     "windfury", "wizard", "mana ", "sharpening stone",
                     "spellpower", "firepower", "agility", "strength",
                     "demonslaying", "mageblood", "draenic")


def _consumable_auras(auras: list[dict]) -> list[str]:
    """Keep only buff names that look like a consumable (drop class buffs etc.)."""
    out = []
    for a in auras or []:
        nm = a.get("name") if isinstance(a, dict) else str(a)
        if nm and any(h in nm.lower() for h in _CONSUMABLE_HINTS):
            out.append(nm)
    return out


def gather_raid_matrix(report_code: str, include_wipes: bool = False) -> RaidMatrix:
    """
    Build the full matrix snapshot for a report. One WCL call for fights/actors/
    abilities, one per-player CombatantInfo (covers all that player's fights), and
    one cast fetch per kill fight for potions. The rate limiter + breaker in
    wcl_client protect the volume.
    """
    from core import wcl_client
    from core.audit.normalize import normalize_combatant
    from core.gear_cache import spec_from_stats, WCL_SPEC_MAP

    m = RaidMatrix(report_code=report_code)

    meta = wcl_client.get_report_meta(report_code)
    fights_all = meta.get("fights") or []
    if not fights_all:
        m.warnings.append("No fights found in that report.")
        return m
    kept = [f for f in fights_all if f.get("kill") or include_wipes]
    if not kept:
        m.warnings.append("No boss kills in that report (use include_wipes to see wipes).")
        return m
    m.fights = [{"id": f["id"], "name": f.get("name", "?"), "kill": bool(f.get("kill"))}
                for f in kept]
    m.zone = meta.get("zone") or ""
    m.start_time = meta.get("start_time")   # absolute epoch ms (report-level)
    kept_ids = {f["id"] for f in kept}

    actors = wcl_client.get_master_actors(report_code)
    actors_by_id = {a["id"]: a for a in actors}

    abilities = wcl_client.get_abilities(report_code)

    # Potions per kill fight (one cast fetch each), tallied per source.
    potions_by_fight: dict[int, dict] = {}
    for f in kept:
        try:
            casts = wcl_client.get_casts(report_code, f["id"])
            potions_by_fight[f["id"]] = _tally_potions(casts, abilities)
        except Exception as e:
            log.warning("matrix potion fetch failed for fight %s: %s", f["id"], e)
            potions_by_fight[f["id"]] = {}

    # Per player: one CombatantInfo fetch covers every fight they were in.
    seen_players: list[dict] = []
    for actor in actors:
        sid = actor["id"]
        name = actor.get("name") or f"src{sid}"
        try:
            events = wcl_client.get_combatant_info(report_code, source_id=sid)
        except Exception as e:
            log.warning("matrix combatant fetch failed for %s: %s", name, e)
            continue
        if not events:
            continue

        # Only include players who appear in at least one kept fight.
        fight_events = {ev.get("fight"): ev for ev in events if ev.get("fight") in kept_ids}
        if not fight_events:
            continue

        cls = actor.get("subType", "")
        # Roster-wide gear: use the most recent kept fight's gear (gems/enchants
        # are stable across the night).
        latest_ev = fight_events[max(fight_events)]
        m.gear[name] = normalize_combatant(latest_ev)

        # Usual spec = most common across this player's kept fights.
        votes: dict[str, int] = {}
        cells: dict[int, Cell] = {}
        for fid, ev in fight_events.items():
            spec = WCL_SPEC_MAP.get(ev.get("specID")) or spec_from_stats(cls, ev)
            if spec:
                votes[spec] = votes.get(spec, 0) + 1
            cells[fid] = Cell(
                auras=_consumable_auras(ev.get("auras")),
                potions=potions_by_fight.get(fid, {}).get(sid, 0),
                spec=spec,
                present=True,
            )
        usual = max(votes, key=votes.get) if votes else None
        m.cells[name] = cells
        seen_players.append({"name": name, "class": cls, "usual_spec": usual})

    m.players = sorted(seen_players, key=lambda p: p["name"])
    return m


def _tally_potions(casts: list[dict], abilities: list[dict]) -> dict:
    """{source_id: potion_count} from cast events (reuses the audit's potion regex)."""
    from core.audit.report import _POTION_RE
    name_by_id = {a.get("gameID"): (a.get("name") or "") for a in abilities}
    out: dict = {}
    for e in casts:
        if e.get("type") != "cast":
            continue
        if _POTION_RE.search(name_by_id.get(e.get("abilityGameID"), "")):
            out[e.get("sourceID")] = out.get(e.get("sourceID"), 0) + 1
    return out
