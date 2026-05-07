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
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

log = logging.getLogger(__name__)

CACHE_DB     = os.path.expanduser("~/.openclaw/data/gear_cache.db")
ITEM_DB_PATH = os.path.expanduser("~/.openclaw/data/tbc_items.db")
MAX_SNAPSHOTS = 5   # per (character, realm, spec)
WCL_TIMEOUT  = 20  # seconds
WOWHEAD_TIMEOUT = 10  # seconds

# ---------------------------------------------------------------------------
# Wowhead TBC item lookup — fires when item_id is missing from tbc_items.db
# ---------------------------------------------------------------------------

# Wowhead inventorySlot id → our DB slot name
_WOWHEAD_INVTYPE_TO_SLOT: dict[int, str] = {
    1: "Head", 2: "Neck", 3: "Shoulder", 5: "Chest", 6: "Waist",
    7: "Legs", 8: "Feet", 9: "Wrist", 10: "Hands", 11: "Ring",
    12: "Trinket", 13: "One Hand", 14: "Off Hand", 15: "Ranged",
    16: "Back", 17: "Two-Hand", 20: "Chest", 21: "Main Hand",
    22: "Off Hand", 23: "Off Hand", 25: "Ranged", 26: "Ranged", 28: "Ranged",
}

# Wowhead armor subclass id → armor_type string
_ARMOR_SUBCLASS: dict[int, str] = {
    1: "Cloth", 2: "Leather", 3: "Mail", 4: "Plate", 6: "Shield",
}

# Wowhead weapon subclass id → weapon_type string
_WEAPON_SUBCLASS: dict[int, str] = {
    0: "Axe", 1: "Axe", 2: "Bow", 3: "Gun", 4: "Mace", 5: "Mace",
    6: "Polearm", 7: "Sword", 8: "Sword", 10: "Staff",
    13: "Fist Weapon", 15: "Dagger", 16: "Thrown", 18: "Crossbow", 19: "Wand",
}

# Tooltip text variants → our canonical stat name (only overrides needed)
_TOOLTIP_STAT_NORM: dict[str, str] = {
    "Spell Damage and Healing":         "Spell Power",
    "Healing and Spell Damage":         "Spell Power",
    "Increases damage and healing":     "Spell Power",
    "Spell Penetration":                "Spell Penetration",
    "Critical Strike Rating":           "Crit Rating",
    "Spell Critical Strike Rating":     "Spell Crit Rating",
    "Spell Hit Rating":                 "Spell Hit Rating",
    "Resilience Rating":                "Resilience",
    "Mana per 5 sec.":                  "MP5",
    "Mana per 5 sec":                   "MP5",
    "Armor Penetration Rating":         "Armor Penetration",
    "Ranged Critical Strike Rating":    "Ranged Crit Rating",
    "Ranged Hit Rating":                "Ranged Hit Rating",
    "Defense Rating":                   "Defense Rating",
    "Dodge Rating":                     "Dodge Rating",
    "Parry Rating":                     "Parry Rating",
    "Block Rating":                     "Block Rating",
    "Block Value":                      "Block Value",
    "Expertise Rating":                 "Expertise Rating",
    "Haste Rating":                     "Haste Rating",
    "Attack Power":                     "Attack Power",
    "Ranged Attack Power":              "Ranged Attack Power",
}

# Stat names that pass through unchanged
_TOOLTIP_STAT_PASSTHROUGH = {
    "Strength", "Agility", "Stamina", "Intellect", "Spirit",
    "Hit Rating", "Armor",
    "Frost Resistance", "Fire Resistance", "Nature Resistance",
    "Arcane Resistance", "Shadow Resistance",
}

# Matches <!--statN-->+16 Stamina or <!--statN-->-5 Armor
_STAT_RE = re.compile(r"<!--stat\d+-->([+-]?\d+)\s+(.+?)(?:<|$|<!)")


def _parse_tooltip_stats(tooltip_html: str) -> dict[str, float]:
    """Extract passive stat bonuses from Wowhead htmlTooltip."""
    stats: dict[str, float] = {}
    for match in _STAT_RE.finditer(tooltip_html):
        try:
            val = float(match.group(1))
        except ValueError:
            continue
        raw_name = match.group(2).strip().rstrip(".")
        stat_name = _TOOLTIP_STAT_NORM.get(raw_name) or (
            raw_name if raw_name in _TOOLTIP_STAT_PASSTHROUGH else None
        )
        if stat_name and val:
            stats[stat_name] = stats.get(stat_name, 0.0) + val
    return stats


def _wowhead_lookup(item_id: int) -> dict | None:
    """
    Fetch item metadata from Wowhead TBC XML API.
    Returns a dict with keys: name, slot, quality, ilvl, stats, armor_type, weapon_type
    or None on any failure.

    Stats come from htmlTooltip <!--statN-->+XX Name patterns.
    Pure proc/use trinkets return stats={} which is correct — no passive bonuses.
    """
    url = f"https://tbc.wowhead.com/item={item_id}&xml"
    try:
        req = Request(url, headers={"User-Agent": "BrnzyBot/1.0"})
        with urlopen(req, timeout=WOWHEAD_TIMEOUT) as resp:
            xml_text = resp.read().decode("utf-8", errors="replace")
    except (URLError, HTTPError, TimeoutError) as e:
        log.warning("Wowhead lookup failed for item %d: %s", item_id, e)
        return None

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        log.warning("Wowhead XML parse error for item %d: %s", item_id, e)
        return None

    item_el = root.find("item")
    if item_el is None:
        log.warning("Wowhead: no <item> element for id %d", item_id)
        return None

    name_el = item_el.find("name")
    name = (name_el.text or "").strip() if name_el is not None else ""
    if not name:
        return None

    quality_el = item_el.find("quality")
    quality = (quality_el.text or "Unknown").strip() if quality_el is not None else "Unknown"

    ilvl_text = item_el.findtext("level", "0")
    try:
        ilvl = int(ilvl_text)
    except ValueError:
        ilvl = 0

    inv_slot_el = item_el.find("inventorySlot")
    inv_slot_id = int(inv_slot_el.get("id", "0")) if inv_slot_el is not None else 0
    slot = _WOWHEAD_INVTYPE_TO_SLOT.get(inv_slot_id, "")

    class_el    = item_el.find("class")
    subclass_el = item_el.find("subclass")
    class_id    = int(class_el.get("id", "-1"))    if class_el    is not None else -1
    subclass_id = int(subclass_el.get("id", "-1")) if subclass_el is not None else -1

    armor_type  = _ARMOR_SUBCLASS.get(subclass_id, "")  if class_id == 4 else ""
    weapon_type = _WEAPON_SUBCLASS.get(subclass_id, "") if class_id == 2 else ""

    tooltip = item_el.findtext("htmlTooltip", "")
    stats = _parse_tooltip_stats(tooltip)

    return {
        "name": name, "slot": slot, "quality": quality, "ilvl": ilvl,
        "stats": stats, "armor_type": armor_type, "weapon_type": weapon_type,
    }


def _insert_unknown_item(item_id: int, item_db_conn: sqlite3.Connection) -> dict | None:
    """
    Look up item_id on Wowhead, insert it into tbc_items.db, and return
    (name, stats_dict, set_name, slot) matching the _fetch_from_wcl tuple format,
    or None if the lookup fails.
    """
    data = _wowhead_lookup(item_id)
    if data is None:
        return None

    try:
        item_db_conn.execute(
            """INSERT OR IGNORE INTO items
               (item_id, name, slot, phase, quality, ilvl, armor_type, weapon_type,
                set_name, is_unique, class_restriction, stats, sockets, socket_bonus,
                source_type, source_name, drop_rate, effort_score)
               VALUES (?, ?, ?, 0, ?, ?, ?, ?, '', 0, '[]', ?, '[]', '{}', '', '', 0, 0)""",
            (
                item_id,
                data["name"],
                data["slot"],
                data["quality"],
                data["ilvl"],
                data["armor_type"],
                data["weapon_type"],
                json.dumps(data["stats"]),
            ),
        )
        item_db_conn.commit()
        log.info(
            "Auto-inserted item %d (%s) from Wowhead — slot=%s stats=%s",
            item_id, data["name"], data["slot"], data["stats"],
        )
    except Exception as e:
        log.warning("Failed to insert item %d into DB: %s", item_id, e)

    return data

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
    faction:     int  = -1  # 0=Horde, 1=Alliance, -1=unknown
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

            # Resolve from local DB; fall back to Wowhead lookup for unknowns
            c.execute("SELECT name, stats, set_name, slot FROM items WHERE item_id = ?", (item_id,))
            row = c.fetchone()
            if row is None:
                looked_up = _insert_unknown_item(item_id, item_db_conn)
                if looked_up:
                    row = (
                        looked_up["name"],
                        json.dumps(looked_up["stats"]),
                        "",
                        looked_up["slot"],
                    )
                    log.info("Resolved previously unknown item %d as %s", item_id, looked_up["name"])
            item_name = row[0] if row else f"Unknown ({item_id})"
            stats     = json.loads(row[1]) if row and row[1] else {}
            set_name  = row[2] if row else ""
            # For ranged/wand/totem/relic position (WCL index 17), prefer the DB's
            # actual slot type so Shamans' totems aren't mislabeled as "Wand"
            if slot == "Wand" and row and row[3] in ("Ranged", "Totem"):
                slot = row[3]

            gear.append({
                "slot":     slot,
                "item_id":  item_id,
                "name":     item_name,
                "stats":    stats,
                "set_name": set_name or "",
            })

        combat_stats = {k: event.get(k, 0) for k in ["hitSpell", "hitMelee", "hitRanged", "critSpell", "hasteSpell"]}
        faction = event.get("faction", -1)

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
            faction=faction,
            from_cache=False,
        )

    except (URLError, HTTPError, KeyError, json.JSONDecodeError, TimeoutError) as e:
        log.warning("WCL fetch failed for %s: %s", name, e)
        return None


# ---------------------------------------------------------------------------
# Spec detection for auto-registration
# ---------------------------------------------------------------------------

# WoW specID → our spec key. These are the Blizzard spec IDs embedded in
# WCL CombatantInfo events. Using specID is far more accurate than guessing
# from classID alone.
WCL_SPEC_MAP: dict[int, str] = {
    # Mage
    62: "arcane_mage", 63: "fire_mage", 64: "frost_mage",
    # Paladin
    65: "holy_paladin", 66: "prot_paladin", 70: "ret_paladin",
    # Warrior
    71: "arms_warrior", 72: "fury_warrior", 73: "prot_warrior",
    # Hunter
    253: "bm_hunter", 254: "mm_hunter", 255: "survival_hunter",
    # Priest
    256: "holy_priest", 257: "holy_priest", 258: "shadow_priest",
    # Rogue
    259: "assassination_rogue", 260: "combat_rogue", 261: "assassination_rogue",
    # Shaman
    262: "ele_shaman", 263: "enh_shaman", 264: "resto_shaman",
    # Warlock
    265: "affliction_warlock", 266: "destro_warlock", 267: "destro_warlock",
    # Druid
    281: "feral_cat_druid", 282: "resto_druid", 283: "balance_druid",
}

# Fallback: classID → most common raiding spec if specID lookup fails
WCL_CLASS_DEFAULT_SPEC = {
    1:  "fury_warrior",
    2:  "ret_paladin",
    3:  "bm_hunter",
    4:  "combat_rogue",
    5:  "shadow_priest",
    7:  "ele_shaman",
    8:  "fire_mage",
    9:  "destro_warlock",
    11: "balance_druid",
}

WCL_CLASS_NAME = {
    1: "Warrior", 2: "Paladin", 3: "Hunter", 4: "Rogue", 5: "Priest",
    7: "Shaman", 8: "Mage", 9: "Warlock", 11: "Druid",
}


_CLASS_NAME_TO_ID: dict[str, int] = {
    "Warrior": 1, "Paladin": 2, "Hunter": 3, "Rogue": 4, "Priest": 5,
    "Shaman": 7, "Mage": 8, "Warlock": 9, "Druid": 11,
}

# Which WCL class IDs can wear each armor type (Rogues/Druids share Leather, etc.)
_ARMOR_CLASS_IDS: dict[str, set[int]] = {
    "Cloth":   {5, 8, 9},       # Priest, Mage, Warlock
    "Leather": {4, 11},         # Rogue, Druid
    "Mail":    {3, 7},          # Hunter, Shaman
    "Plate":   {1, 2},          # Warrior, Paladin
}


def _infer_class_from_gear_ids(item_ids: list[int]) -> int | None:
    """
    Query the item DB for class_restriction on equipped items.
    Returns the WCL class ID if deterministic, None if ambiguous or unavailable.

    Class-restricted items (e.g. Collar of the Aldor = Mage only) take priority.
    Armor type is used as a tiebreaker only if it uniquely narrows to one class.
    """
    if not item_ids or not os.path.exists(ITEM_DB_PATH):
        return None
    try:
        db = sqlite3.connect(ITEM_DB_PATH)
        placeholders = ",".join("?" * len(item_ids))
        rows = db.execute(
            f"SELECT class_restriction, armor_type FROM items"
            f" WHERE item_id IN ({placeholders})",
            item_ids,
        ).fetchall()
        db.close()
    except Exception as e:
        log.debug("Gear class inference DB query failed: %s", e)
        return None

    class_votes: dict[int, int] = {}
    armor_counts: dict[str, int] = {}

    for class_restr_json, armor_type in rows:
        try:
            restrictions = json.loads(class_restr_json or "[]")
        except Exception:
            restrictions = []
        for class_name in restrictions:
            cid = _CLASS_NAME_TO_ID.get(class_name)
            if cid:
                class_votes[cid] = class_votes.get(cid, 0) + 1
        if armor_type:
            armor_counts[armor_type] = armor_counts.get(armor_type, 0) + 1

    if class_votes:
        best = max(class_votes, key=class_votes.get)
        log.debug("Gear class inference: class_votes=%s → classID=%d", class_votes, best)
        return best

    # No class-restricted items — try armor type (only definitive if one class fits)
    if armor_counts:
        top_armor = max(armor_counts, key=armor_counts.get)
        candidates = _ARMOR_CLASS_IDS.get(top_armor, set())
        if len(candidates) == 1:
            return next(iter(candidates))

    return None


def fetch_class_id(name: str, realm: str, region: str = "us") -> tuple[int | None, str | None]:
    """
    Returns (classID, display_name) from WCL. Used for auto-registration fallback.
    Prefer fetch_character_spec() which also resolves the specific spec.
    """
    result = fetch_character_spec(name, realm, region)
    if result is None:
        return None, None
    display_name, spec_key, class_id = result
    return class_id, display_name


def fetch_character_spec(
    name: str, realm: str, region: str = "us"
) -> tuple[str, str, int] | None:
    """
    Query WCL for a character's actual spec from their most recent log.

    Returns (display_name, spec_key, class_id) or None on any failure.

    Strategy:
      1. Get classID + most recent report code from the character endpoint.
      2. Get the actor ID from the report's master data.
      3. Read the last CombatantInfo event to get specID.
      4. Map specID → spec_key via WCL_SPEC_MAP.
      5. Fall back to WCL_CLASS_DEFAULT_SPEC if specID lookup fails.
    """
    client_id     = os.environ.get("WCL_CLIENT_ID", "")
    client_secret = os.environ.get("WCL_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return None

    try:
        token = _get_token(client_id, client_secret)

        # Step 1: classID + recent report
        r1 = _wcl_query(token, f'''{{
            characterData {{
                character(name: "{name}", serverSlug: "{realm}", serverRegion: "{region}") {{
                    classID
                    name
                    recentReports(limit: 1) {{ data {{ code startTime }} }}
                }}
            }}
        }}''')
        char = r1["data"]["characterData"]["character"]
        if not char:
            log.warning("WCL spec lookup: no character found for %s@%s/%s", name, realm, region)
            return None

        class_id     = char["classID"]
        display_name = char["name"]
        reports      = char["recentReports"]["data"]
        log.info("WCL spec lookup: %s@%s → classID=%d name=%s reports=%d",
                 name, realm, class_id, display_name, len(reports))

        if not reports:
            # No logs at all — fall back to class default
            spec_key = WCL_CLASS_DEFAULT_SPEC.get(class_id)
            if not spec_key:
                return None
            log.warning("No WCL reports for %s — using class default %s", display_name, spec_key)
            return display_name, spec_key, class_id

        code = reports[0]["code"]

        # Step 2: actor ID
        r2 = _wcl_query(token, f'''{{
            reportData {{ report(code: "{code}") {{
                masterData {{ actors(type: "Player") {{ id name }} }}
            }} }}
        }}''')
        actor_id = None
        for actor in r2["data"]["reportData"]["report"]["masterData"]["actors"]:
            if actor["name"].lower() == display_name.lower():
                actor_id = actor["id"]
                break

        if not actor_id:
            log.warning("WCL spec lookup: actor %s not in report %s", display_name, code)
            spec_key = WCL_CLASS_DEFAULT_SPEC.get(class_id)
            return (display_name, spec_key, class_id) if spec_key else None

        # Step 3: CombatantInfo specID
        r3 = _wcl_query(token, f'''{{
            reportData {{ report(code: "{code}") {{
                events(sourceID: {actor_id}, dataType: CombatantInfo,
                       startTime: 0, endTime: 999999999999) {{ data }}
            }} }}
        }}''')
        events = r3["data"]["reportData"]["report"]["events"]["data"]
        spec_key = None
        if events:
            event    = events[-1]
            spec_id  = event.get("specID")
            spec_key = WCL_SPEC_MAP.get(spec_id)
            log.info("WCL spec lookup: %s specID=%s → %s", display_name, spec_id, spec_key)

            # Cross-validate WCL classID against equipped gear class restrictions.
            # Private servers sometimes return wrong classIDs — gear doesn't lie.
            gear_ids = [g.get("id", 0) for g in event.get("gear", []) if g.get("id")]
            inferred = _infer_class_from_gear_ids(gear_ids)
            if inferred and inferred != class_id:
                log.warning(
                    "WCL classID=%d (%s) contradicted by gear (inferred classID=%d, %s) "
                    "— trusting gear",
                    class_id, WCL_CLASS_NAME.get(class_id, "?"),
                    inferred, WCL_CLASS_NAME.get(inferred, "?"),
                )
                class_id = inferred
                spec_key = None   # re-derive below using corrected class

        if not spec_key:
            spec_key = WCL_CLASS_DEFAULT_SPEC.get(class_id)
            log.warning("WCL spec lookup: specID unknown for %s — using class default %s",
                        display_name, spec_key)

        if not spec_key:
            return None
        return display_name, spec_key, class_id

    except (URLError, HTTPError, KeyError, json.JSONDecodeError, TimeoutError) as e:
        log.warning("WCL spec lookup failed for %s@%s: %s", name, realm, e)
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
