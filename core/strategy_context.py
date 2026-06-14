"""
strategy_context.py — deterministic strategy DB lookup and prompt block builder.

Mirrors gear_context.py in structure: pure pre-computation, no LLM calls.
Returns a rendered string suitable for injection into a model prompt as ground truth.

Public API:
    get_strategy_context(query: str) -> str
    search_boss(query: str) -> dict | None   (for cog use)
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from dataclasses import dataclass, field

import config

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    if not os.path.exists(config.STRATEGY_DB_PATH):
        raise FileNotFoundError(
            f"Strategy DB not found at {config.STRATEGY_DB_PATH}. "
            "Run: python3 build_strategy_db.py"
        )
    conn = sqlite3.connect(config.STRATEGY_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _fts_query(raw: str) -> str:
    """Build a safe FTS5 match expression from a raw user query."""
    # Strip characters that break FTS5 syntax
    clean = re.sub(r'["\'\(\)\*\:]', '', raw).strip()
    tokens = clean.split()
    if not tokens:
        return '""'
    # Phrase search on full input, fallback to OR of individual tokens
    phrase = '"' + ' '.join(tokens) + '"'
    individual = ' OR '.join(tokens)
    return f'{phrase} OR {individual}'


def _lookup_boss_by_name(conn: sqlite3.Connection, query: str,
                         max_phase: int | None = None) -> sqlite3.Row | None:
    fts = _fts_query(query)
    phase_clause = " AND b.phase <= ?" if max_phase is not None else ""
    params = (fts, max_phase) if max_phase is not None else (fts,)
    try:
        row = conn.execute(
            f"""SELECT b.* FROM bosses b
               JOIN bosses_fts f ON b.boss_id = f.rowid
               WHERE bosses_fts MATCH ?{phase_clause}
               ORDER BY rank LIMIT 1""",
            params,
        ).fetchone()
        return row
    except sqlite3.OperationalError:
        return None


def _lookup_boss_by_ability(conn: sqlite3.Connection, query: str,
                            max_phase: int | None = None) -> sqlite3.Row | None:
    """Find a boss via ability FTS — useful for 'what is Enfeeble' queries."""
    fts = _fts_query(query)
    phase_clause = " AND b.phase <= ?" if max_phase is not None else ""
    params = (fts, max_phase) if max_phase is not None else (fts,)
    try:
        row = conn.execute(
            f"""SELECT b.* FROM bosses b
               JOIN abilities a ON a.boss_id = b.boss_id
               JOIN abilities_fts af ON a.ability_id = af.rowid
               WHERE abilities_fts MATCH ?{phase_clause}
               ORDER BY af.rank LIMIT 1""",
            params,
        ).fetchone()
        return row
    except sqlite3.OperationalError:
        return None


def _lookup_boss_by_zone(conn: sqlite3.Connection, query: str,
                         max_phase: int | None = None) -> list[sqlite3.Row]:
    """Return all bosses for a matched zone name."""
    clean = query.lower()
    zone_keywords = {
        "karazhan": "karazhan",
        "kara": "karazhan",
        "gruul": "gruuls_lair",
        "gruul's": "gruuls_lair",
        "magtheridon": "magtheridon",
        "mag": "magtheridon",
        "serpentshrine": "serpentshrine_cavern",
        "ssc": "serpentshrine_cavern",
        "tempest keep": "tempest_keep",
        "the eye": "tempest_keep",
        "tk": "tempest_keep",
        "hyjal": "mount_hyjal",
        "black temple": "black_temple",
        "bt": "black_temple",
        "zul'aman": "zulaman",
        "zulaman": "zulaman",
        "zul aman": "zulaman",
        "za": "zulaman",
    }
    zone_slug = None
    for keyword, slug in zone_keywords.items():
        if keyword in clean:
            zone_slug = slug
            break
    if not zone_slug:
        return []
    phase_clause = " AND phase <= ?" if max_phase is not None else ""
    params = (zone_slug, max_phase) if max_phase is not None else (zone_slug,)
    return conn.execute(
        f"SELECT * FROM bosses WHERE zone_slug = ?{phase_clause} ORDER BY boss_id",
        params,
    ).fetchall()


def _get_abilities(conn: sqlite3.Connection, boss_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM abilities WHERE boss_id = ? ORDER BY important DESC, ability_id",
        (boss_id,),
    ).fetchall()


# ---------------------------------------------------------------------------
# Context dataclass
# ---------------------------------------------------------------------------

@dataclass
class StrategyContext:
    query:       str
    boss:        dict | None
    abilities:   list[dict] = field(default_factory=list)
    zone_bosses: list[dict] = field(default_factory=list)
    matched_by:  str = "no_match"   # boss_name | ability_name | zone | no_match

    def found(self) -> bool:
        return self.boss is not None or bool(self.zone_bosses)

    def to_prompt_block(self) -> str:
        if not self.found():
            return (
                f"## Strategy Context\n\n"
                f"No strategy data found for query: '{self.query}'.\n"
                "The knowledge base covers Karazhan, Gruul's Lair, and Magtheridon (Phase 1)."
            )

        if self.zone_bosses and not self.boss:
            return self._zone_summary_block()

        return self._boss_detail_block()

    def _zone_summary_block(self) -> str:
        zone_name = self.zone_bosses[0]["zone"]
        lines = [f"## Strategy Context: {zone_name} — Boss List", ""]
        for b in self.zone_bosses:
            lines.append(f"- **{b['name']}**: {b['summary'][:120]}...")
        lines += [
            "",
            "Ask about a specific boss for full strategy detail, abilities, and role notes.",
        ]
        return "\n".join(lines)

    def _boss_detail_block(self) -> str:
        b = self.boss
        lines = [
            f"## Strategy Context: {b['name']} — {b['zone']} (Phase {b['phase']})",
            "",
            f"**Summary:** {b['summary']}",
        ]

        # Phases
        phases = b.get("phases", [])
        if phases:
            lines += ["", "### Phases"]
            for p in phases:
                pname = p.get("name") or f"Phase {p.get('number', '')}"
                lines.append(
                    f"**{pname} "
                    f"({p.get('hp_range', '')}):** {p.get('description', '')}"
                )

        # Abilities
        if self.abilities:
            lines += ["", "### Abilities"]
            for ab in self.abilities:
                priority = " ⚠ HIGH PRIORITY" if ab["important"] else ""
                lines.append(
                    f"**{ab['name']}** [{ab['mechanic_type']}, targets: {ab['targets']}{priority}]"
                )
                lines.append(ab["description"])
                lines.append("")

        # Strategies
        strategies = b.get("strategies", [])
        if strategies:
            lines += ["### Strategy Variants"]
            for s in strategies:
                lines.append(f"**{s['name']}** ({', '.join(s.get('applicable_to', ['all']))})")
                lines.append(s["summary"])
                if s.get("notes"):
                    lines.append(f"*Note: {s['notes']}*")
                lines.append("")

        # Roles
        roles = b.get("roles", {})
        if roles:
            lines += ["### Role Notes"]
            if roles.get("tank"):
                lines.append(f"**Tanks:** {roles['tank']}")
                lines.append("")
            if roles.get("healer"):
                lines.append(f"**Healers:** {roles['healer']}")
                lines.append("")
            if roles.get("dps"):
                lines.append(f"**DPS:** {roles['dps']}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _build_context(query: str, max_phase: int | None = None) -> StrategyContext:
    """Build strategy context for a query. If max_phase is given, bosses from a
    later content phase are excluded (so future-raid content stays hidden until
    the realm reaches that phase). None = no gate (used by tests / offline tools)."""
    try:
        conn = _connect()
    except FileNotFoundError as e:
        log.warning("Strategy DB unavailable: %s", e)
        return StrategyContext(query=query, boss=None)

    try:
        # 1. Try direct boss name search
        row = _lookup_boss_by_name(conn, query, max_phase)
        if row:
            abilities = _get_abilities(conn, row["boss_id"])
            boss = dict(row)
            boss["phases"]     = json.loads(boss.get("phases_json",     "[]"))
            boss["strategies"] = json.loads(boss.get("strategies_json", "[]"))
            boss["roles"]      = json.loads(boss.get("roles_json",      "{}"))
            return StrategyContext(
                query=query,
                boss=boss,
                abilities=[dict(a) for a in abilities],
                matched_by="boss_name",
            )

        # 2. Try ability name search (e.g. "what is Enfeeble")
        row = _lookup_boss_by_ability(conn, query, max_phase)
        if row:
            abilities = _get_abilities(conn, row["boss_id"])
            boss = dict(row)
            boss["phases"]     = json.loads(boss.get("phases_json",     "[]"))
            boss["strategies"] = json.loads(boss.get("strategies_json", "[]"))
            boss["roles"]      = json.loads(boss.get("roles_json",      "{}"))
            return StrategyContext(
                query=query,
                boss=boss,
                abilities=[dict(a) for a in abilities],
                matched_by="ability_name",
            )

        # 3. Zone summary (e.g. "what bosses are in Karazhan")
        zone_rows = _lookup_boss_by_zone(conn, query, max_phase)
        if zone_rows:
            return StrategyContext(
                query=query,
                boss=None,
                zone_bosses=[dict(r) for r in zone_rows],
                matched_by="zone",
            )

        return StrategyContext(query=query, boss=None)

    finally:
        conn.close()


def get_strategy_context(query: str, max_phase: int | None = None) -> str:
    """Return a prompt-ready strategy context block for the given query.
    max_phase gates out later-phase content (None = no gate)."""
    ctx = _build_context(query, max_phase)
    return ctx.to_prompt_block()


def search_boss(query: str, max_phase: int | None = None) -> dict | None:
    """Return the matched boss dict (with parsed JSON fields) or None. Used by cogs."""
    ctx = _build_context(query, max_phase)
    return ctx.boss
