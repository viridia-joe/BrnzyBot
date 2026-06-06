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
import time
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
    """Create tables and apply column migrations. Safe to call on every startup."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(SCHEMA_PATH) as f:
        schema = f.read()
    with sqlite3.connect(path) as conn:
        conn.executescript(schema)
        _migrate(conn)


# Columns added after initial deploy — ALTER TABLE is idempotent via try/except.
_MIGRATIONS = [
    "ALTER TABLE guild_config ADD COLUMN current_phase INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE guild_config ADD COLUMN interest_threshold INTEGER NOT NULL DEFAULT 5",
    "ALTER TABLE server_config ADD COLUMN recap_channel_id TEXT",
    "ALTER TABLE guild_config ADD COLUMN officer_role_id TEXT",
    "ALTER TABLE guild_config ADD COLUMN botduel_log_channel_id TEXT",
    "ALTER TABLE guild_config ADD COLUMN heartbeat_channel_id TEXT",
    "ALTER TABLE guild_config ADD COLUMN last_haiku_ts INTEGER",
]


def _migrate(conn: sqlite3.Connection) -> None:
    for stmt in _MIGRATIONS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # column already exists


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


def set_guild_phase(guild_id: str, phase: int, path: str = DB_PATH) -> None:
    with _conn(path) as conn:
        conn.execute(
            """INSERT INTO guild_config (guild_id, current_phase)
               VALUES (?, ?)
               ON CONFLICT (guild_id)
               DO UPDATE SET current_phase=excluded.current_phase""",
            (guild_id, phase),
        )


def get_guild_phase(guild_id: str, path: str = DB_PATH) -> int:
    with _conn(path) as conn:
        row = conn.execute(
            "SELECT current_phase FROM guild_config WHERE guild_id=?", (guild_id,)
        ).fetchone()
    return row["current_phase"] if row else 1


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


def fuzzy_match_character(
    guild_id: str, name: str, cutoff: float = 0.65, path: str = DB_PATH
) -> str | None:
    """
    Return the best-matching registered character name for a guild, or None.

    Uses difflib sequence matching — cutoff 0.65 catches one-or-two character
    typos ("shermshaman" → "Shermnshamn") without producing false positives on
    short names.
    """
    from difflib import get_close_matches
    chars = list_characters(guild_id, path=path)
    if not chars:
        return None
    known = [c["display_name"] for c in chars]
    matches = get_close_matches(name.lower(), [n.lower() for n in known], n=1, cutoff=cutoff)
    if not matches:
        return None
    # Return the original-cased display name
    match_lower = matches[0]
    return next((n for n in known if n.lower() == match_lower), None)


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


# ---------------------------------------------------------------------------
# Usage logging + metering
# ---------------------------------------------------------------------------

def log_usage(guild_id: str, user_id: str, command: str, path: str = DB_PATH) -> None:
    with _conn(path) as conn:
        conn.execute(
            "INSERT INTO usage_log (guild_id, user_id, command) VALUES (?, ?, ?)",
            (guild_id, user_id, command),
        )


def count_usage_today(guild_id: str, path: str = DB_PATH) -> int:
    """Count how many commands this guild has run today (UTC)."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    with _conn(path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM usage_log WHERE guild_id=? AND logged_at >= ?",
            (guild_id, today),
        ).fetchone()
    return row["n"] if row else 0


def count_command_month(guild_id: str, command: str, path: str = DB_PATH) -> int:
    """Count how many times this guild ran a given command this calendar month (UTC)."""
    month = datetime.utcnow().strftime("%Y-%m-01")
    with _conn(path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM usage_log WHERE guild_id=? AND command=? AND logged_at >= ?",
            (guild_id, command, month),
        ).fetchone()
    return row["n"] if row else 0

FREE_DAILY_LIMIT = 20  # commands per guild per day on free plan


def get_subscription(guild_id: str, path: str = DB_PATH) -> dict:
    with _conn(path) as conn:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE guild_id=?", (guild_id,)
        ).fetchone()
    return dict(row) if row else {"guild_id": guild_id, "plan": "free", "status": "active"}


def upsert_subscription(
    guild_id: str,
    plan: str,
    status: str,
    stripe_customer_id: Optional[str] = None,
    stripe_sub_id: Optional[str] = None,
    path: str = DB_PATH,
) -> None:
    with _conn(path) as conn:
        conn.execute(
            """INSERT INTO subscriptions
               (guild_id, plan, status, stripe_customer_id, stripe_sub_id, updated_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT (guild_id)
               DO UPDATE SET plan=excluded.plan,
                             status=excluded.status,
                             stripe_customer_id=COALESCE(excluded.stripe_customer_id, stripe_customer_id),
                             stripe_sub_id=COALESCE(excluded.stripe_sub_id, stripe_sub_id),
                             updated_at=excluded.updated_at""",
            (guild_id, plan, status, stripe_customer_id, stripe_sub_id),
        )


def is_pro(guild_id: str, path: str = DB_PATH) -> bool:
    sub = get_subscription(guild_id, path)
    return sub["plan"] == "pro" and sub["status"] in ("active", "trialing")


def check_rate_limit(guild_id: str, path: str = DB_PATH) -> tuple[bool, int]:
    """
    Returns (allowed, remaining).
    Pro guilds are always allowed. Free guilds capped at FREE_DAILY_LIMIT/day.
    """
    if is_pro(guild_id, path):
        return True, 999
    used = count_usage_today(guild_id, path)
    remaining = max(0, FREE_DAILY_LIMIT - used)
    return remaining > 0, remaining


# ---------------------------------------------------------------------------
# Per-user custom stat weights
# ---------------------------------------------------------------------------

def get_user_weights(
    guild_id: str, user_id: str, spec: str, path: str = DB_PATH
) -> Optional[dict]:
    with _conn(path) as conn:
        row = conn.execute(
            "SELECT weights_json FROM user_weights WHERE guild_id=? AND user_id=? AND spec=?",
            (guild_id, user_id, spec),
        ).fetchone()
    return json.loads(row["weights_json"]) if row else None


def set_user_weights(
    guild_id: str, user_id: str, spec: str, weights: dict, path: str = DB_PATH
) -> None:
    with _conn(path) as conn:
        conn.execute(
            """INSERT INTO user_weights (guild_id, user_id, spec, weights_json, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'))
               ON CONFLICT (guild_id, user_id, spec)
               DO UPDATE SET weights_json=excluded.weights_json,
                             updated_at=excluded.updated_at""",
            (guild_id, user_id, spec, json.dumps(weights)),
        )


def delete_user_weights(
    guild_id: str, user_id: str, path: str = DB_PATH
) -> None:
    with _conn(path) as conn:
        conn.execute(
            "DELETE FROM user_weights WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )


# ---------------------------------------------------------------------------
# GDPR — full guild/user data deletion
# ---------------------------------------------------------------------------

def delete_guild_data(guild_id: str, path: str = DB_PATH) -> None:
    """Hard-delete all stored data for a guild."""
    with _conn(path) as conn:
        for table in ("server_config", "guild_config", "characters",
                      "pending_intents", "usage_log", "subscriptions", "user_weights",
                      "duels", "gold_ledger"):
            conn.execute(f"DELETE FROM {table} WHERE guild_id=?", (guild_id,))


def delete_user_data(guild_id: str, user_id: str, path: str = DB_PATH) -> None:
    """Hard-delete all stored data for a specific user in a guild."""
    with _conn(path) as conn:
        conn.execute(
            "DELETE FROM usage_log WHERE guild_id=? AND user_id=?", (guild_id, user_id)
        )
        conn.execute(
            "DELETE FROM user_weights WHERE guild_id=? AND user_id=?", (guild_id, user_id)
        )
        conn.execute(
            "DELETE FROM characters WHERE guild_id=? AND added_by=?", (guild_id, user_id)
        )
        conn.execute(
            "DELETE FROM pending_intents WHERE guild_id=? AND user_id=?", (guild_id, user_id)
        )


def purge_expired_intents(path: str = DB_PATH) -> int:
    now = datetime.utcnow().isoformat()
    with _conn(path) as conn:
        cur = conn.execute(
            "DELETE FROM pending_intents WHERE expires_at <= ?", (now,)
        )
    return cur.rowcount


# ---------------------------------------------------------------------------
# BotDuel — guild config extras
# ---------------------------------------------------------------------------

def set_heartbeat_channel(guild_id: str, channel_id: str, path: str = DB_PATH) -> None:
    with _conn(path) as conn:
        conn.execute(
            """INSERT INTO guild_config (guild_id, heartbeat_channel_id) VALUES (?, ?)
               ON CONFLICT (guild_id) DO UPDATE SET heartbeat_channel_id=excluded.heartbeat_channel_id""",
            (guild_id, channel_id),
        )


def get_heartbeat_channel(guild_id: str, path: str = DB_PATH) -> Optional[str]:
    with _conn(path) as conn:
        row = conn.execute(
            "SELECT heartbeat_channel_id FROM guild_config WHERE guild_id=?", (guild_id,)
        ).fetchone()
    return row["heartbeat_channel_id"] if row else None


def get_last_haiku_ts(guild_id: str, path: str = DB_PATH) -> Optional[int]:
    with _conn(path) as conn:
        row = conn.execute(
            "SELECT last_haiku_ts FROM guild_config WHERE guild_id=?", (guild_id,)
        ).fetchone()
    return row["last_haiku_ts"] if row else None


def set_last_haiku_ts(guild_id: str, ts: int, path: str = DB_PATH) -> None:
    with _conn(path) as conn:
        conn.execute(
            """INSERT INTO guild_config (guild_id, last_haiku_ts) VALUES (?, ?)
               ON CONFLICT (guild_id) DO UPDATE SET last_haiku_ts=excluded.last_haiku_ts""",
            (guild_id, ts),
        )


def set_officer_role(guild_id: str, role_id: str, path: str = DB_PATH) -> None:
    with _conn(path) as conn:
        conn.execute(
            """INSERT INTO guild_config (guild_id, officer_role_id) VALUES (?, ?)
               ON CONFLICT (guild_id) DO UPDATE SET officer_role_id=excluded.officer_role_id""",
            (guild_id, role_id),
        )


def get_officer_role(guild_id: str, path: str = DB_PATH) -> Optional[str]:
    with _conn(path) as conn:
        row = conn.execute(
            "SELECT officer_role_id FROM guild_config WHERE guild_id=?", (guild_id,)
        ).fetchone()
    return row["officer_role_id"] if row else None


def set_botduel_log_channel(guild_id: str, channel_id: str, path: str = DB_PATH) -> None:
    with _conn(path) as conn:
        conn.execute(
            """INSERT INTO guild_config (guild_id, botduel_log_channel_id) VALUES (?, ?)
               ON CONFLICT (guild_id) DO UPDATE SET botduel_log_channel_id=excluded.botduel_log_channel_id""",
            (guild_id, channel_id),
        )


def get_botduel_log_channel(guild_id: str, path: str = DB_PATH) -> Optional[str]:
    with _conn(path) as conn:
        row = conn.execute(
            "SELECT botduel_log_channel_id FROM guild_config WHERE guild_id=?", (guild_id,)
        ).fetchone()
    return row["botduel_log_channel_id"] if row else None


# ---------------------------------------------------------------------------
# BotDuel — duel lifecycle
# ---------------------------------------------------------------------------

def create_duel(
    guild_id: str,
    challenger: str,
    opponent: str,
    gold_stake: int,
    created_at: int,
    expires_at: int,
    path: str = DB_PATH,
) -> int:
    with _conn(path) as conn:
        cur = conn.execute(
            """INSERT INTO duels (guild_id, challenger, opponent, gold_stake, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (guild_id, challenger, opponent, gold_stake, created_at, expires_at),
        )
        return cur.lastrowid


def get_duel(duel_id: int, guild_id: Optional[str] = None, path: str = DB_PATH) -> Optional[dict]:
    with _conn(path) as conn:
        if guild_id:
            row = conn.execute(
                "SELECT * FROM duels WHERE id=? AND guild_id=?", (duel_id, guild_id)
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM duels WHERE id=?", (duel_id,)).fetchone()
    return dict(row) if row else None


def update_duel(duel_id: int, path: str = DB_PATH, **fields) -> None:
    if not fields:
        return
    set_clause = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [duel_id]
    with _conn(path) as conn:
        conn.execute(f"UPDATE duels SET {set_clause} WHERE id=?", values)


def get_open_duels(
    guild_id: str,
    user_id: Optional[str] = None,
    status: Optional[str] = None,
    path: str = DB_PATH,
) -> list[dict]:
    terminal = ("completed", "declined", "expired")
    with _conn(path) as conn:
        if status:
            if user_id:
                rows = conn.execute(
                    """SELECT * FROM duels WHERE guild_id=? AND status=?
                       AND (challenger=? OR opponent=?) ORDER BY id DESC""",
                    (guild_id, status, user_id, user_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM duels WHERE guild_id=? AND status=? ORDER BY id DESC",
                    (guild_id, status),
                ).fetchall()
        elif user_id:
            rows = conn.execute(
                """SELECT * FROM duels WHERE guild_id=? AND status NOT IN (?,?,?)
                   AND (challenger=? OR opponent=?) ORDER BY id DESC""",
                (guild_id, *terminal, user_id, user_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM duels WHERE guild_id=? AND status NOT IN (?,?,?) ORDER BY id DESC",
                (guild_id, *terminal),
            ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# BotDuel — gold ledger
# ---------------------------------------------------------------------------

def add_ledger_entry(
    guild_id: str,
    user_id: str,
    delta: int,
    reason: str,
    duel_id: Optional[int] = None,
    path: str = DB_PATH,
) -> None:
    now = int(time.time())
    with _conn(path) as conn:
        conn.execute(
            """INSERT INTO gold_ledger (guild_id, user_id, delta, reason, duel_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (guild_id, user_id, delta, reason, duel_id, now),
        )


def get_gold_balance(guild_id: str, user_id: str, path: str = DB_PATH) -> int:
    with _conn(path) as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(delta), 0) AS bal FROM gold_ledger WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        ).fetchone()
    return row["bal"] if row else 0


def get_leaderboard(guild_id: str, limit: int = 10, path: str = DB_PATH) -> list[dict]:
    with _conn(path) as conn:
        rows = conn.execute(
            """SELECT user_id, SUM(delta) AS net_gold
               FROM gold_ledger WHERE guild_id=?
               GROUP BY user_id ORDER BY net_gold DESC LIMIT ?""",
            (guild_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_player_record(guild_id: str, user_id: str, path: str = DB_PATH) -> dict:
    with _conn(path) as conn:
        wins = conn.execute(
            "SELECT COUNT(*) AS n FROM duels WHERE guild_id=? AND winner=? AND status='completed'",
            (guild_id, user_id),
        ).fetchone()["n"]
        total = conn.execute(
            """SELECT COUNT(*) AS n FROM duels
               WHERE guild_id=? AND status='completed' AND (challenger=? OR opponent=?)""",
            (guild_id, user_id, user_id),
        ).fetchone()["n"]
        bal_row = conn.execute(
            "SELECT COALESCE(SUM(delta), 0) AS bal FROM gold_ledger WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        ).fetchone()
    return {"wins": wins, "losses": total - wins, "net_gold": bal_row["bal"]}
