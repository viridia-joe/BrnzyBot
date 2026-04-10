"""
OpenClaw Raid Analyst — SQLite manifest.

Tracks which WCL report codes have been seen and processed.
Also stores per-death repeat-offense history and boss kill history
for cross-report tracking.

Hardening (Phase 6):
  - retry_count + last_error columns on reports table
  - prune_old_reports() removes reports older than 90 days
  - write_heartbeat() / check_heartbeat() for cron health monitoring
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))
import config

_HEARTBEAT_FILE  = os.path.join(config.DATA_DIR, "heartbeat.json")
_MAX_RETRIES     = 3
_PRUNE_DAYS      = 90   # keep processed reports for 90 days
_DEATH_PRUNE_DAYS = 90  # keep death history for repeat-offender window


def _connect() -> sqlite3.Connection:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(config.MANIFEST_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables and apply any missing schema migrations."""
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS reports (
                code            TEXT PRIMARY KEY,
                title           TEXT,
                start_time      INTEGER,
                end_time        INTEGER,
                discovered_at   TEXT NOT NULL,
                processed       INTEGER NOT NULL DEFAULT 0,
                interest_score  INTEGER,
                night_outcome   TEXT,
                retry_count     INTEGER NOT NULL DEFAULT 0,
                last_error      TEXT
            );

            -- Per-death history for repeat-offender detection.
            CREATE TABLE IF NOT EXISTS death_history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                report_code     TEXT NOT NULL,
                raid_date       TEXT NOT NULL,
                player_name     TEXT NOT NULL,
                boss_name       TEXT NOT NULL,
                death_category  TEXT NOT NULL,
                avoidable       INTEGER NOT NULL DEFAULT 1
            );

            CREATE INDEX IF NOT EXISTS idx_death_history_player
                ON death_history (player_name, boss_name, death_category);

            -- Boss kill history for regression detection.
            CREATE TABLE IF NOT EXISTS boss_kill_history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                report_code     TEXT NOT NULL,
                raid_date       TEXT NOT NULL,
                boss_name       TEXT NOT NULL,
                encounter_id    INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_boss_kill_history
                ON boss_kill_history (boss_name, raid_date);
        """)

        # Schema migration: add retry_count / last_error if upgrading from Phase 1-5
        existing = {row[1] for row in conn.execute("PRAGMA table_info(reports)")}
        if "retry_count" not in existing:
            conn.execute("ALTER TABLE reports ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0")
        if "last_error" not in existing:
            conn.execute("ALTER TABLE reports ADD COLUMN last_error TEXT")


def get_known_codes() -> set[str]:
    """Return the set of all report codes in the manifest."""
    with _connect() as conn:
        rows = conn.execute("SELECT code FROM reports").fetchall()
    return {r["code"] for r in rows}


def add_reports(reports: list[dict]) -> list[dict]:
    """
    Insert new reports into the manifest.
    `reports` is a list of dicts with keys: code, title, startTime, endTime.
    Returns only the newly inserted reports.
    """
    known = get_known_codes()
    now   = datetime.now(timezone.utc).isoformat()
    new_reports = []

    with _connect() as conn:
        for r in reports:
            if r["code"] in known:
                continue
            conn.execute(
                """
                INSERT INTO reports (code, title, start_time, end_time, discovered_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (r["code"], r.get("title"), r.get("startTime"), r.get("endTime"), now),
            )
            new_reports.append(r)

    return new_reports


def get_unprocessed() -> list[sqlite3.Row]:
    """
    Return reports not yet processed, skipping ones that have hit the retry cap.
    Ordered oldest-first so we process in chronological order.
    """
    with _connect() as conn:
        return conn.execute(
            """
            SELECT * FROM reports
            WHERE processed = 0 AND retry_count < ?
            ORDER BY start_time ASC
            """,
            (_MAX_RETRIES,),
        ).fetchall()


def mark_processed(code: str, interest_score: int = None, night_outcome: str = None) -> None:
    """Mark a report as successfully processed."""
    with _connect() as conn:
        conn.execute(
            """
            UPDATE reports
            SET processed = 1, interest_score = ?, night_outcome = ?, last_error = NULL
            WHERE code = ?
            """,
            (interest_score, night_outcome, code),
        )


def record_failure(code: str, error: str) -> None:
    """
    Increment retry_count and store the error message.
    After _MAX_RETRIES failures the report is silently skipped by get_unprocessed().
    """
    with _connect() as conn:
        conn.execute(
            """
            UPDATE reports
            SET retry_count = retry_count + 1,
                last_error  = ?
            WHERE code = ?
            """,
            (error[:500], code),
        )


def record_death(
    report_code: str,
    raid_date:   str,
    player_name: str,
    boss_name:   str,
    death_category: str,
    avoidable:   bool,
) -> None:
    """Store a classified death for repeat-offender tracking."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO death_history
                (report_code, raid_date, player_name, boss_name, death_category, avoidable)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (report_code, raid_date, player_name, boss_name, death_category, int(avoidable)),
        )


def record_kills(report_code: str, raid_date: str, kills: list[dict]) -> None:
    """
    Store boss kills for regression detection.
    `kills` is a list of dicts with keys: boss_name, encounter_id.
    """
    with _connect() as conn:
        for kill in kills:
            conn.execute(
                """
                INSERT INTO boss_kill_history (report_code, raid_date, boss_name, encounter_id)
                VALUES (?, ?, ?, ?)
                """,
                (report_code, raid_date, kill["boss_name"], kill["encounter_id"]),
            )


def get_historically_killed_bosses(before_date: str) -> set[str]:
    """
    Return boss names killed in any report before `before_date` (YYYY-MM-DD).
    Used to detect regression: wiping on a previously killed boss.
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT boss_name FROM boss_kill_history WHERE raid_date < ?",
            (before_date,),
        ).fetchall()
    return {r["boss_name"] for r in rows}


def get_repeat_count(player_name: str, boss_name: str, death_category: str, weeks: int = 3) -> int:
    """
    Return how many times this player has died to the same cause on the same boss
    in the last `weeks` weeks. Used for repeat-offender interest score bonus.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(weeks=weeks)).isoformat()[:10]
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) as cnt FROM death_history
            WHERE player_name   = ?
              AND boss_name      = ?
              AND death_category = ?
              AND avoidable      = 1
              AND raid_date     >= ?
            """,
            (player_name, boss_name, death_category, cutoff),
        ).fetchone()
    return row["cnt"] if row else 0


# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------
def prune_old_data() -> tuple[int, int]:
    """
    Delete processed reports and associated history older than _PRUNE_DAYS.
    Boss kill history is kept permanently (needed for regression detection).
    Returns (reports_deleted, deaths_deleted).
    """
    cutoff_ts  = int((datetime.now(timezone.utc) - timedelta(days=_PRUNE_DAYS)).timestamp() * 1000)
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=_DEATH_PRUNE_DAYS)).isoformat()[:10]

    with _connect() as conn:
        old_codes = [
            r["code"] for r in conn.execute(
                "SELECT code FROM reports WHERE processed = 1 AND start_time < ?",
                (cutoff_ts,),
            ).fetchall()
        ]

        reports_deleted = 0
        deaths_deleted  = 0

        for code in old_codes:
            conn.execute("DELETE FROM death_history WHERE report_code = ?", (code,))
            deaths_deleted += conn.execute(
                "SELECT changes()"
            ).fetchone()[0]
            conn.execute("DELETE FROM reports WHERE code = ?", (code,))
            reports_deleted += 1

        # Also prune orphaned death_history rows beyond the repeat-detection window
        result = conn.execute(
            "DELETE FROM death_history WHERE raid_date < ?", (cutoff_date,)
        )
        deaths_deleted += result.rowcount

    return reports_deleted, deaths_deleted


# ---------------------------------------------------------------------------
# Health heartbeat
# ---------------------------------------------------------------------------
def write_heartbeat() -> None:
    """Write a timestamp file after each successful poller run."""
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(_HEARTBEAT_FILE, "w") as f:
        json.dump({"last_run": datetime.now(timezone.utc).isoformat()}, f)


def check_heartbeat(warn_after_hours: int = 2) -> tuple[bool, str]:
    """
    Return (healthy, message).
    healthy=False if the last run was more than warn_after_hours ago or
    the heartbeat file doesn't exist.
    """
    try:
        with open(_HEARTBEAT_FILE) as f:
            data = json.load(f)
        last_run = datetime.fromisoformat(data["last_run"])
        age = datetime.now(timezone.utc) - last_run
        if age > timedelta(hours=warn_after_hours):
            return False, f"Last run was {age} ago (threshold: {warn_after_hours}h)"
        return True, f"Last run: {last_run.isoformat()}"
    except FileNotFoundError:
        return False, "Heartbeat file not found — poller has never run successfully"
    except Exception as e:
        return False, f"Heartbeat check error: {e}"
