"""
BrnzyBot Gear Cache — WCL fetch with SQLite fallback.

Fetches current gear from WCL. On failure (503, timeout, rate limit), serves
the most recent cached snapshot for the character+spec combination. Cache stores
the last 5 snapshots per (character, realm, spec) so situational sets (e.g. a
healer's healing set) are preserved across rare usage.

Entry points:
    get_gear(name, realm, spec, region="us") -> GearSnapshot | None
    cache_snapshot(snapshot: GearSnapshot) -> None
"""

import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

log = logging.getLogger(__name__)

CACHE_DB = os.path.expanduser("~/.openclaw/data/gear_cache.db")
MAX_SNAPSHOTS = 5   # per (character, realm, spec)
WCL_TIMEOUT  = 20  # seconds

# ---------------------------------------------------------------------------
# Data structure
# ---------------------------------------------------------------------------
@dataclass
class GearSnapshot:
    character:  str
    realm:      str
    spec:       str
    region:     str
    report_code: str
    report_time: int        # WCL ms timestamp
    fetched_at:  int        # Unix timestamp (seconds)
    gear:        list       # list of {slot, item_id, name, stats, set_name}
    combat_stats: dict      # hitSpell, critSpell, hasteSpell from WCL
    from_cache:  bool = False


# ---------------------------------------------------------------------------
# Cache DB
# ---------------------------------------------------------------------------
def _init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gear_snapshots (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            character    TEXT NOT NULL,
            realm        TEXT NOT NULL,
            spec         TEXT NOT NULL,
            region       TEXT NOT NULL DEFAULT 'us',
            report_code  TEXT,
            report_time  INTEGER,
            fetched_at   INTEGER NOT NULL,
            gear_json    TEXT NOT NULL,
            combat_stats TEXT NOT NULL DEFAULT '{}'
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_char_spec
        ON gear_snapshots (character, realm, spec, fetched_at DESC)
    """)
    conn.commit()


def _get_conn():
    os.makedirs(os.path.dirname(CACHE_DB), exist_ok=True)
    conn = sqlite3.connect(CACHE_DB)
    _init_db(conn)
    return conn


def cache_snapshot(snapshot: GearSnapshot) -> None:
    """Persist a snapshot and prune old ones beyond MAX_SNAPSHOTS."""
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO gear_snapshots
                (character, realm, spec, region, report_code, report_time,
                 fetched_at, gear_json, combat_stats)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            snapshot.character.lower(),
            snapshot.realm.lower(),
            snapshot.spec.lower(),
            snapshot.region.lower(),
            snapshot.report_code,
            snapshot.report_time,
            snapshot.fetched_at,
            json.dumps(snapshot.gear),
            json.dumps(snapshot.combat_stats),
        ))
        conn.commit()

        # Prune: keep only the most recent MAX_SNAPSHOTS per key
        conn.execute("""
            DELETE FROM gear_snapshots
            WHERE character = ? AND realm = ? AND spec = ?
              AND id NOT IN (
                  SELECT id FROM gear_snapshots
                  WHERE character = ? AND realm = ? AND spec = ?
                  ORDER BY fetched_at DESC
                  LIMIT ?
              )
        """, (
            snapshot.character.lower(), snapshot.realm.lower(), snapshot.spec.lower(),
            snapshot.character.lower(), snapshot.realm.lower(), snapshot.spec.lower(),
            MAX_SNAPSHOTS,
        ))
        conn.commit()
    finally:
        conn.close()


def load_cached(name: str, realm: str, spec: str, region: str = "us") -> GearSnapshot | None:
    """Return the most recent cached snapshot, or None."""
    conn = _get_conn()
    try:
        row = conn.execute("""
            SELECT report_code, report_time, fetched_at, gear_json, combat_stats
            FROM gear_snapshots
            WHERE character = ? AND realm = ? AND spec = ?
            ORDER BY fetched_at DESC
            LIMIT 1
        """, (name.lower(), realm.lower(), spec.lower())).fetchone()
    finally:
        conn.close()

    if not row:
        return None

    return GearSnapshot(
        character=name,
        realm=realm,
        spec=spec,
        region=region,
        report_code=row[0] or "",
        report_time=row[1] or 0,
        fetched_at=row[2],
        gear=json.loads(row[3]),
        combat_stats=json.loads(row[4]),
        from_cache=True,
    )


# ---------------------------------------------------------------------------
# WCL API helpers (stdlib only)
# ---------------------------------------------------------------------------
def _http_post(url, data=None, json_data=None, headers=None):
    hdrs = headers or {}
    if json_data is not None:
        body = json.dumps(json_data).encode()
        hdrs["Content-Type"] = "application/json"
    elif data is not None:
        body = urlencode(data).encode()
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    else:
        body = b""
    req = Request(url, data=body, headers=hdrs, method="POST")
    with urlopen(req, timeout=WCL_TIMEOUT) as resp:
        return json.loads(resp.read())


def _get_token(client_id: str, client_secret: str) -> str:
    return _http_post(
        "https://www.warcraftlogs.com/oauth/token",
        data={
            "grant_type":    "client_credentials",
            "client_id":     client_id,
            "client_secret": client_secret,
        },
    )["access_token"]


def _wcl_query(token: str, query: str) -> dict:
    return _http_post(
        "https://classic.warcraftlogs.com/api/v2/client",
        json_data={"query": query},
        headers={"Authorization": f"Bearer {token}"},
    )


WCL_SLOT_MAP = {
    0: "Head", 1: "Neck", 2: "Shoulder", 4: "Chest", 5: "Waist",
    6: "Legs", 7: "Feet", 8: "Wrist", 9: "Hands", 10: "Ring",
    11: "Ring", 12: "Trinket", 13: "Trinket", 14: "Back",
    15: "Main Hand", 16: "Off Hand", 17: "Wand",
}


def _fetch_from_wcl(name: str, realm: str, spec: str, region: str,
                    client_id: str, client_secret: str,
                    item_db_conn) -> GearSnapshot | None:
    """Fetch live gear from WCL. Returns None on any failure."""
    try:
        token = _get_token(client_id, client_secret)

        # Most recent report
        result = _wcl_query(token, f'''{{
            characterData {{
                character(name: "{name}", serverSlug: "{realm}", serverRegion: "{region}") {{
                    classID
                    recentReports(limit: 1) {{ data {{ code startTime }} }}
                }}
            }}
        }}''')
        char = result["data"]["characterData"]["character"]
        if not char or not char["recentReports"]["data"]:
            log.warning("WCL: no reports found for %s@%s", name, realm)
            return None

        report = char["recentReports"]["data"][0]
        code   = report["code"]
        rtime  = report["startTime"]

        # Actor ID
        result = _wcl_query(token, f'''{{
            reportData {{ report(code: "{code}") {{
                masterData {{ actors(type: "Player") {{ id name }} }}
            }} }}
        }}''')
        actor_id = None
        for actor in result["data"]["reportData"]["report"]["masterData"]["actors"]:
            if actor["name"].lower() == name.lower():
                actor_id = actor["id"]
                break

        if not actor_id:
            log.warning("WCL: actor %s not found in report %s", name, code)
            return None

        # CombatantInfo event
        result = _wcl_query(token, f'''{{
            reportData {{ report(code: "{code}") {{
                events(sourceID: {actor_id}, dataType: CombatantInfo,
                       startTime: 0, endTime: 999999999999) {{ data }}
            }} }}
        }}''')
        events = result["data"]["reportData"]["report"]["events"]["data"]
        if not events:
            log.warning("WCL: no CombatantInfo for %s in %s", name, code)
            return None

        event = events[-1]
        gear  = []

        c = item_db_conn.cursor()
        for i, gear_item in enumerate(event.get("gear", [])):
            item_id = gear_item.get("id", 0)
            slot    = WCL_SLOT_MAP.get(i)
            if not slot or item_id == 0:
                continue

            # Resolve from local DB — no external calls
            c.execute("SELECT name, stats, set_name FROM items WHERE item_id = ?", (item_id,))
            row = c.fetchone()
            item_name = row[0] if row else f"Unknown ({item_id})"
            stats     = json.loads(row[1]) if row and row[1] else {}
            set_name  = row[2] if row else ""

            gear.append({
                "slot":     slot,
                "item_id":  item_id,
                "name":     item_name,
                "stats":    stats,
                "set_name": set_name or "",
            })

        combat_stats = {k: event.get(k, 0) for k in ["hitSpell", "critSpell", "hasteSpell"]}

        return GearSnapshot(
            character=name,
            realm=realm,
            spec=spec,
            region=region,
            report_code=code,
            report_time=rtime,
            fetched_at=int(time.time()),
            gear=gear,
            combat_stats=combat_stats,
            from_cache=False,
        )

    except (URLError, HTTPError, KeyError, json.JSONDecodeError, TimeoutError) as e:
        log.warning("WCL fetch failed for %s: %s", name, e)
        return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def get_gear(name: str, realm: str, spec: str, region: str = "us",
             item_db_conn=None) -> GearSnapshot | None:
    """
    Fetch current gear for a character.

    Tries WCL first; falls back to cache on any failure.
    Returns None only if both WCL and cache fail.

    item_db_conn: open sqlite3 connection to tbc_items.db (for name/stat resolution)
    """
    client_id     = os.environ.get("WCL_CLIENT_ID", "")
    client_secret = os.environ.get("WCL_CLIENT_SECRET", "")

    snapshot = None

    if client_id and client_secret and item_db_conn:
        snapshot = _fetch_from_wcl(name, realm, spec, region,
                                   client_id, client_secret, item_db_conn)
        if snapshot:
            cache_snapshot(snapshot)
            log.info("Gear fetched from WCL for %s (%s)", name, spec)
            return snapshot

    # WCL failed or creds missing — try cache
    cached = load_cached(name, realm, spec, region)
    if cached:
        age_h = (time.time() - cached.fetched_at) / 3600
        log.warning(
            "WCL unavailable — serving cached gear for %s (%s), %.1fh old",
            name, spec, age_h
        )
        return cached

    log.error("No gear available for %s@%s spec=%s — WCL failed and no cache", name, realm, spec)
    return None
