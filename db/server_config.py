"""
BrnzyBot per-server configuration store.

Single SQLite database (brnzybot.db) holding:
  - Per (guild, channel) verbosity + response target settings
  - Per-guild WoW realm / region
  - Character registry (maps display names to specs)
  - Pending intent queue (awaiting clarification responses)

All functions are synchronous — call from a thread executor if needed in
async contexts, or use the async wrappers in db/async_config.py.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional

DB_PATH = os.path.expanduser("~/.openclaw/data/brnzybot.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

VALID_VERBOSITY = {"silent", "commands_only", "speak_when_spoken_to", "chatty"}
VALID_RESPONSE_TARGET = {"channel", "ephemeral", "dm"}


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

def init_db(path: str = DB_PATH) -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(SCHEMA_PATH) as f:
        schema = f.read()
    with sqlite3.connect(path) as conn:
        conn.executescript(schema)


@contextmanager
def _conn(path: str = DB_PATH):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Verbosity / channel config
# ---------------------------------------------------------------------------

def get_verbosity(guild_id: str, channel_id: str, path: str = DB_PATH) -> str:
    """Return verbosity mode for this guild+channel. Defaults to speak_when_spoken_to."""
    with _conn(path) as conn:
        row = conn.execute(
            "SELECT verbosity FROM server_config WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        ).fetchone()
    return row["verbosity"] if row else "speak_when_spoken_to"


def set_verbosity(
    guild_id: str, channel_id: str, verbosity: str, path: str = DB_PATH
) -> None:
    if verbosity not in VALID_VERBOSITY:
        raise ValueError(f"Invalid verbosity {verbosity!r}. Choose from: {VALID_VERBOSITY}")
    with _conn(path) as conn:
        conn.execute(
            """INSERT INTO server_config (guild_id, channel_id, verbosity)
               VALUES (?, ?, ?)
               ON CONFLICT (guild_id, channel_id)
               DO UPDATE SET verbosity = excluded.verbosity""",
            (guild_id, channel_id, verbosity),
        )


def get_response_target(guild_id: str, channel_id: str, path: str = DB_PATH) -> str:
    with _conn(path) as conn:
        row = conn.execute(
            "SELECT response_target FROM server_config WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        ).fetchone()
    return row["response_target"] if row else "channel"


def set_response_target(
    guild_id: str, channel_id: str, target: str, path: str = DB_PATH
) -> None:
    if target not in VALID_RESPONSE_TARGET:
        raise ValueError(f"Invalid target {target!r}. Choose from: {VALID_RESPONSE_TARGET}")
    with _conn(path) as conn:
        conn.execute(
            """INSERT INTO server_config (guild_id, channel_id, response_target)
               VALUES (?, ?, ?)
               ON CONFLICT (guild_id, channel_id)
               DO UPDATE SET response_target = excluded.response_target""",
            (guild_id, channel_id, target),
        )


# ---------------------------------------------------------------------------
# Guild config
# ---------------------------------------------------------------------------

def get_guild_config(guild_id: str, path: str = DB_PATH) -> Optional[dict]:
    with _conn(path) as conn:
        row = conn.execute(
            "SELECT * FROM guild_config WHERE guild_id=?", (guild_id,)
        ).fetchone()
    return dict(row) if row else None


def set_guild_config(
    guild_id: str,
    guild_name: str,
    server_slug: str,
    region: str = "us",
    path: str = DB_PATH,
) -> None:
    with _conn(path) as conn:
        conn.execute(
            """INSERT INTO guild_config (guild_id, guild_name, server_slug, region)
               VALUES (?, ?, ?, ?)
               ON CONFLICT (guild_id)
               DO UPDATE SET guild_name=excluded.guild_name,
                             server_slug=excluded.server_slug,
                             region=excluded.region""",
            (guild_id, guild_name, server_slug, region),
        )


# ---------------------------------------------------------------------------
# Character registry
# ---------------------------------------------------------------------------

def add_character(
    guild_id: str,
    name: str,
    spec: str,
    realm: str,
    region: str = "us",
    added_by: Optional[str] = None,
    path: str = DB_PATH,
) -> None:
    with _conn(path) as conn:
        conn.execute(
            """INSERT INTO characters
               (guild_id, name_lower, display_name, spec, realm, region, added_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (guild_id, name_lower)
               DO UPDATE SET spec=excluded.spec, realm=excluded.realm,
                             region=excluded.region, added_by=excluded.added_by""",
            (guild_id, name.lower(), name, spec, realm, region, added_by),
        )


def get_character(
    guild_id: str, name: str, path: str = DB_PATH
) -> Optional[dict]:
    with _conn(path) as conn:
        row = conn.execute(
            "SELECT * FROM characters WHERE guild_id=? AND name_lower=?",
            (guild_id, name.lower()),
        ).fetchone()
    return dict(row) if row else None


def list_characters(guild_id: str, path: str = DB_PATH) -> list[dict]:
    with _conn(path) as conn:
        rows = conn.execute(
            "SELECT * FROM characters WHERE guild_id=? ORDER BY display_name",
            (guild_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def remove_character(guild_id: str, name: str, path: str = DB_PATH) -> bool:
    with _conn(path) as conn:
        cur = conn.execute(
            "DELETE FROM characters WHERE guild_id=? AND name_lower=?",
            (guild_id, name.lower()),
        )
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Pending intents (awaiting clarification)
# ---------------------------------------------------------------------------

def store_pending_intent(
    guild_id: str,
    channel_id: str,
    user_id: str,
    intent: dict,
    prompt: str,
    ttl_seconds: int = 120,
    path: str = DB_PATH,
) -> None:
    expires = (datetime.utcnow() + timedelta(seconds=ttl_seconds)).isoformat()
    with _conn(path) as conn:
        # One pending intent per user per channel — overwrite old one
        conn.execute(
            "DELETE FROM pending_intents WHERE guild_id=? AND channel_id=? AND user_id=?",
            (guild_id, channel_id, user_id),
        )
        conn.execute(
            """INSERT INTO pending_intents
               (guild_id, channel_id, user_id, intent_json, prompt, expires_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (guild_id, channel_id, user_id, json.dumps(intent), prompt, expires),
        )


def pop_pending_intent(
    guild_id: str, channel_id: str, user_id: str, path: str = DB_PATH
) -> Optional[dict]:
    """Retrieve and delete a pending intent if it hasn't expired."""
    now = datetime.utcnow().isoformat()
    with _conn(path) as conn:
        row = conn.execute(
            """SELECT id, intent_json FROM pending_intents
               WHERE guild_id=? AND channel_id=? AND user_id=? AND expires_at > ?""",
            (guild_id, channel_id, user_id, now),
        ).fetchone()
        if row:
            conn.execute("DELETE FROM pending_intents WHERE id=?", (row["id"],))
            return json.loads(row["intent_json"])
    return None


def purge_expired_intents(path: str = DB_PATH) -> int:
    now = datetime.utcnow().isoformat()
    with _conn(path) as conn:
        cur = conn.execute(
            "DELETE FROM pending_intents WHERE expires_at <= ?", (now,)
        )
    return cur.rowcount
