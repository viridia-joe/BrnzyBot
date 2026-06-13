#!/usr/bin/env python3
"""
build_strategy_db.py — compile strategy JSON files into tbc_strategy.db

Run standalone:
    python3 build_strategy_db.py [--data-dir /path/to/data/strategy] [--db /path/to/db]

Reads all *.json files from STRATEGY_DATA_DIR, creates/refreshes the SQLite
database at STRATEGY_DB_PATH.  Fully idempotent — safe to re-run any time.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS bosses (
    boss_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    slug            TEXT    NOT NULL UNIQUE,
    name            TEXT    NOT NULL,
    zone            TEXT    NOT NULL,
    zone_slug       TEXT    NOT NULL,
    phase           INTEGER NOT NULL DEFAULT 1,
    encounter_id    INTEGER,
    summary         TEXT    NOT NULL DEFAULT '',
    phases_json     TEXT    NOT NULL DEFAULT '[]',
    strategies_json TEXT    NOT NULL DEFAULT '[]',
    roles_json      TEXT    NOT NULL DEFAULT '{}',
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_bosses_zone  ON bosses (zone_slug);
CREATE INDEX IF NOT EXISTS idx_bosses_phase ON bosses (phase);

CREATE TABLE IF NOT EXISTS abilities (
    ability_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    boss_id       INTEGER NOT NULL REFERENCES bosses(boss_id),
    name          TEXT    NOT NULL,
    mechanic_type TEXT    NOT NULL DEFAULT 'special',
    targets       TEXT    NOT NULL DEFAULT 'raid',
    description   TEXT    NOT NULL,
    important     INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_abilities_boss     ON abilities (boss_id);
CREATE INDEX IF NOT EXISTS idx_abilities_mechanic ON abilities (mechanic_type);

-- FTS5 virtual tables for search
CREATE VIRTUAL TABLE IF NOT EXISTS bosses_fts USING fts5(
    slug, name, zone, summary,
    content='bosses',
    content_rowid='boss_id',
    tokenize='unicode61 remove_diacritics 1'
);

CREATE VIRTUAL TABLE IF NOT EXISTS abilities_fts USING fts5(
    name, description,
    content='abilities',
    content_rowid='ability_id',
    tokenize='unicode61 remove_diacritics 1'
);

-- Keep FTS in sync
CREATE TRIGGER IF NOT EXISTS bosses_fts_ins AFTER INSERT ON bosses BEGIN
    INSERT INTO bosses_fts(rowid, slug, name, zone, summary)
    VALUES (new.boss_id, new.slug, new.name, new.zone, new.summary);
END;

CREATE TRIGGER IF NOT EXISTS bosses_fts_del BEFORE DELETE ON bosses BEGIN
    INSERT INTO bosses_fts(bosses_fts, rowid, slug, name, zone, summary)
    VALUES ('delete', old.boss_id, old.slug, old.name, old.zone, old.summary);
END;

CREATE TRIGGER IF NOT EXISTS abilities_fts_ins AFTER INSERT ON abilities BEGIN
    INSERT INTO abilities_fts(rowid, name, description)
    VALUES (new.ability_id, new.name, new.description);
END;

CREATE TRIGGER IF NOT EXISTS abilities_fts_del BEFORE DELETE ON abilities BEGIN
    INSERT INTO abilities_fts(abilities_fts, rowid, name, description)
    VALUES ('delete', old.ability_id, old.name, old.description);
END;
"""

REQUIRED_BOSS_FIELDS = {"name", "slug", "summary", "abilities", "strategies", "roles"}


def _load_zone(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _validate_boss(boss: dict, zone_slug: str) -> list[str]:
    errors = []
    for field in REQUIRED_BOSS_FIELDS:
        if field not in boss:
            errors.append(f"  [{boss.get('slug', '?')}] missing field: {field}")
    return errors


def build(db_path: str, data_dir: str) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()

    json_files = sorted(Path(data_dir).glob("*.json"))
    if not json_files:
        log.warning("No JSON files found in %s", data_dir)
        return

    total_bosses = 0
    total_abilities = 0
    errors_found = []

    for path in json_files:
        zone_data = _load_zone(str(path))
        meta = zone_data.get("_meta", {})
        # Unified store: a file may carry bossguide-only content not yet verified
        # for /strat (e.g. relocated, un-researched raids). strat_index=False keeps
        # it out of the FTS DB while bossguide still reads it from the JSON.
        if not meta.get("strat_index", True):
            log.info("  Skipping %s for /strat FTS (strat_index=false)", path.name)
            continue
        zone_name = meta.get("zone", path.stem.replace("_", " ").title())
        zone_slug = meta.get("zone_slug", path.stem)
        phase     = meta.get("phase", 1)

        for boss in zone_data.get("bosses", []):
            errs = _validate_boss(boss, zone_slug)
            if errs:
                errors_found.extend(errs)
                continue

            slug = boss["slug"]

            # Delete existing (triggers clean up FTS)
            cur = conn.execute("SELECT boss_id FROM bosses WHERE slug = ?", (slug,))
            row = cur.fetchone()
            if row:
                conn.execute("DELETE FROM abilities WHERE boss_id = ?", (row[0],))
                conn.execute("DELETE FROM bosses WHERE boss_id = ?", (row[0],))

            # Insert boss
            conn.execute(
                """INSERT INTO bosses
                   (slug, name, zone, zone_slug, phase, encounter_id,
                    summary, phases_json, strategies_json, roles_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    slug,
                    boss["name"],
                    zone_name,
                    zone_slug,
                    boss.get("phase", phase),
                    boss.get("encounter_id"),
                    boss["summary"],
                    json.dumps(boss.get("phases", [])),
                    json.dumps(boss["strategies"]),
                    json.dumps(boss["roles"]),
                ),
            )
            boss_id = conn.execute(
                "SELECT boss_id FROM bosses WHERE slug = ?", (slug,)
            ).fetchone()[0]

            # Insert abilities
            for ab in boss["abilities"]:
                conn.execute(
                    """INSERT INTO abilities
                       (boss_id, name, mechanic_type, targets, description, important)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        boss_id,
                        ab["name"],
                        ab.get("mechanic_type", "special"),
                        ab.get("targets", "raid"),
                        ab["description"],
                        int(ab.get("important", False)),
                    ),
                )
                total_abilities += 1

            total_bosses += 1
            log.info("  Loaded %-30s  (%d abilities)", boss["name"], len(boss["abilities"]))

    conn.commit()
    conn.close()

    if errors_found:
        for e in errors_found:
            log.warning("Validation error: %s", e)

    print(
        f"Strategy DB built: {total_bosses} bosses, {total_abilities} abilities "
        f"from {len(json_files)} zone file(s).\n  -> {db_path}"
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # Try to use config defaults; gracefully fall back if running outside the repo
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import config as cfg
        default_db   = cfg.STRATEGY_DB_PATH
        default_data = cfg.STRATEGY_DATA_DIR
    except Exception:
        default_db   = os.path.expanduser("~/.openclaw/data/tbc_strategy.db")
        default_data = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "strategy")

    parser = argparse.ArgumentParser(description="Build TBC strategy SQLite DB from JSON files")
    parser.add_argument("--db",       default=default_db,   help="Path to output SQLite DB")
    parser.add_argument("--data-dir", default=default_data, help="Directory containing zone JSON files")
    args = parser.parse_args()

    build(args.db, args.data_dir)


if __name__ == "__main__":
    main()
