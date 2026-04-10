#!/usr/bin/env python3
"""
fix_item_sources.py — Backfill source_name / source_type for TBC items.

Reads items from ~/.openclaw/data/tbc_items.db where source_name is NULL/empty
and phase >= 1, fetches structured source data from the Wowhead TBC XML API,
then writes source_name and source_type back to the DB.

Wowhead endpoint used:
    https://tbc.wowhead.com/item=ITEMID&xml

The response is an XML document. Inside it is a <json> CDATA block containing
a JavaScript-style object literal. That JSON blob includes a "sourcemore" array
with objects like:
    {"t": 1, "n": "Gruul the Dragonkiller", "ti": 2677, "z": "Gruul's Lair"}

Source type integers (field "t"):
    1 = Drop (mob)
    2 = Quest
    3 = Vendor
    4 = Crafted / Recipe
    6 = Badge / Currency purchase

Usage:
    python3 fix_item_sources.py               # live run
    python3 fix_item_sources.py --dry-run     # print what would be written, no DB writes
    python3 fix_item_sources.py --limit 50    # process at most 50 items
    python3 fix_item_sources.py --item 28802  # single item for testing

Bloodmaw Magus-Blade (item_id=28802):
    Drops from Gruul the Dragonkiller in Gruul's Lair (25-man raid, phase 1).
    source_name = "Gruul's Lair - Gruul the Dragonkiller"
    source_type = "Raid"
"""

from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import sys
import time
import json as _json
from typing import Optional
import urllib.request
import urllib.error
import os

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DB_PATH = os.path.expanduser("~/.openclaw/data/tbc_items.db")
BASE_URL = "https://www.wowhead.com/classic/item={item_id}&xml"
ALT_URL  = "https://tbc.wowhead.com/item={item_id}&xml"
RATE_LIMIT_SECONDS = 1.0
REQUEST_TIMEOUT = 15
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds between retries on transient errors

# Full browser-like headers — Cloudflare blocks bare Python UA
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
EXTRA_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.wowhead.com/",
    "DNT": "1",
    "Connection": "keep-alive",
}

# ---------------------------------------------------------------------------
# Source type map: wowhead integer → human label
# ---------------------------------------------------------------------------
SOURCE_TYPE_MAP = {
    1: "Drop",       # mob / boss drop
    2: "Quest",      # quest reward
    3: "Vendor",     # vendor purchase (usually gold)
    4: "Crafted",    # crafted by profession recipe
    6: "Badge",      # badge / currency (Badge of Justice, etc.)
    7: "Drop",       # world drop (treat same as Drop)
    8: "Drop",       # zone drop
}

# Instance names → raid/dungeon classification.
# Keys are substrings that appear in wowhead zone names.
RAID_INSTANCES = {
    "Karazhan", "Gruul", "Magtheridon", "Serpentshrine", "Tempest Keep",
    "The Eye", "Hyjal", "Black Temple", "Sunwell", "Zul'Aman",
    "Zul'Gurub",  # present in TBC for some items
}
HEROIC_KEYWORDS = {"Heroic", "heroic"}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Wowhead fetch + parse
# ---------------------------------------------------------------------------

def _fetch_xml(item_id: int) -> Optional[str]:
    """Fetch the XML document for an item from Wowhead TBC. Returns raw XML string or None."""
    import gzip, io
    headers = {"User-Agent": USER_AGENT, **EXTRA_HEADERS}

    for url_template in (BASE_URL, ALT_URL):
        url = url_template.format(item_id=item_id)
        req = urllib.request.Request(url, headers=headers)

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                    raw = resp.read()
                    # Decompress gzip if needed
                    if resp.info().get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
                    text = raw.decode("utf-8", errors="replace")
                    if "<json>" in text:
                        return text
                    log.debug("item %d: response has no <json> block", item_id)
                    return text  # return anyway for debugging
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    log.info("item %d: 404 on %s", item_id, url_template)
                    break  # try next URL template
                if exc.code in (403, 429, 503):
                    log.warning("item %d: HTTP %d on attempt %d — rate limited?", item_id, exc.code, attempt)
                else:
                    log.warning("item %d: HTTPError %d on attempt %d", item_id, exc.code, attempt)
            except urllib.error.URLError as exc:
                log.warning("item %d: URLError %s on attempt %d", item_id, exc.reason, attempt)
            except Exception as exc:  # noqa: BLE001
                log.warning("item %d: unexpected error on attempt %d: %s", item_id, attempt, exc)

            if attempt < MAX_RETRIES:
                log.info("item %d: retrying in %ds…", item_id, RETRY_DELAY)
                time.sleep(RETRY_DELAY)

    return None


def _extract_json_block(xml: str) -> Optional[dict]:
    """
    Pull the <json> CDATA block out of the Wowhead XML response and parse it.

    The block looks like:
        <json><![CDATA[  {"name":"...","sourcemore":[...], ...}  ]]></json>

    Wowhead wraps it in CDATA so it isn't valid JSON by itself — we strip the
    outer wrapper and parse the inner object.
    """
    # Match the <json> CDATA section
    m = re.search(r"<json><!\[CDATA\[(.*?)\]\]></json>", xml, re.DOTALL)
    if not m:
        return None
    raw = m.group(1).strip()

    # Wowhead sometimes omits quotes around numeric keys or uses single quotes;
    # in practice the block is valid JSON — but strip any trailing JS semicolons.
    raw = raw.rstrip(";")
    try:
        return _json.loads(raw)
    except _json.JSONDecodeError:
        # Attempt a lenient fix: replace single-quoted strings
        # (rare but happens on some older items)
        try:
            fixed = re.sub(r"(?<![\\])'", '"', raw)
            return _json.loads(fixed)
        except _json.JSONDecodeError:
            return None


def _classify_source_type(source_int: int, zone_name: str) -> str:
    """
    Map a wowhead source integer + zone name to a human-readable source_type.
    """
    if source_int == 2:
        return "Quest"
    if source_int in (3,):
        return "Vendor"
    if source_int == 4:
        return "Crafted"
    if source_int == 6:
        return "Badge"

    # source_int == 1 (or 7/8) is a drop — distinguish raid vs heroic vs dungeon
    if source_int in (1, 7, 8):
        if zone_name:
            for raid_kw in RAID_INSTANCES:
                if raid_kw.lower() in zone_name.lower():
                    return "Raid"
            for hkw in HEROIC_KEYWORDS:
                if hkw in zone_name:
                    return "Heroic Dungeon"
        return "Dungeon"  # default drop type

    return "Drop"


def _build_source_name(boss_name: str, zone_name: str) -> str:
    """Format 'Zone - Boss' or just 'Zone' if no boss."""
    if zone_name and boss_name and boss_name.lower() != zone_name.lower():
        return f"{zone_name} - {boss_name}"
    return zone_name or boss_name or ""


def get_item_source(item_id: int) -> tuple[Optional[str], Optional[str]]:
    """
    Fetch and parse source data for item_id from Wowhead TBC.

    Returns (source_name, source_type) or (None, None) if not found/parseable.

    source_name examples:
        "Gruul's Lair - Gruul the Dragonkiller"
        "The Eye - Void Reaver"
        "Badge of Justice"
        "Quest: The Vials of Eternity"
        "Tailoring"

    source_type examples:
        "Raid", "Dungeon", "Heroic Dungeon", "Badge", "Quest", "Crafted", "Vendor"
    """
    xml = _fetch_xml(item_id)
    if xml is None:
        return None, None

    data = _extract_json_block(xml)
    if data is None:
        log.debug("item %d: could not parse <json> block", item_id)
        return None, None

    # -------------------------------------------------------------------
    # Priority 1: "sourcemore" array — most structured
    # Each entry: {"t": INT, "n": "Boss Name", "ti": ZONE_ID, "z": "Zone", ...}
    # -------------------------------------------------------------------
    sourcemore = data.get("sourcemore", [])
    if sourcemore and isinstance(sourcemore, list):
        # Pick the first entry (primary source); skip vendor/world-drop fallbacks
        # when a boss drop entry exists
        boss_entry = next(
            (e for e in sourcemore if isinstance(e, dict) and e.get("t") == 1),
            None,
        )
        entry = boss_entry or sourcemore[0]
        if isinstance(entry, dict):
            t         = entry.get("t", 1)
            boss      = entry.get("n", "").strip()
            zone      = entry.get("z", "").strip()

            # Badge items: wowhead puts the currency name in "n"
            if t == 6:
                return boss or "Badge of Justice", "Badge"

            # Quest items
            if t == 2:
                label = f"Quest: {boss}" if boss else "Quest"
                return label, "Quest"

            # Crafted
            if t == 4:
                # "n" is the recipe/profession name for crafted items
                return boss or "Crafted", "Crafted"

            # Vendor
            if t == 3:
                label = f"{zone} - {boss}" if zone and boss else (zone or boss or "Vendor")
                return label, "Vendor"

            # Drop (t=1, 7, 8)
            source_name = _build_source_name(boss, zone)
            source_type = _classify_source_type(t, zone)
            if source_name:
                return source_name, source_type

    # -------------------------------------------------------------------
    # Priority 2: top-level "source" integer + "sourcemore" zone fallback
    # -------------------------------------------------------------------
    source_int = data.get("source")
    if source_int is not None:
        # Try to get zone from "contentPhase" or other fields
        zone = data.get("contentPhase", "")
        source_type = _classify_source_type(int(source_int), str(zone))
        return None, source_type  # partial — no boss name available

    log.debug("item %d: no sourcemore and no source field", item_id)
    return None, None


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def fetch_items_needing_source(conn: sqlite3.Connection, limit: Optional[int] = None) -> list[tuple[int, str]]:
    """Return list of (item_id, name) where source_name is missing and phase >= 1."""
    sql = """
        SELECT item_id, name
          FROM items
         WHERE (source_name IS NULL OR source_name = '')
           AND phase >= 1
         ORDER BY phase ASC, item_id ASC
    """
    if limit:
        sql += f" LIMIT {limit}"
    cur = conn.execute(sql)
    return cur.fetchall()


def update_item_source(
    conn: sqlite3.Connection,
    item_id: int,
    source_name: str,
    source_type: str,
    dry_run: bool = False,
) -> None:
    if dry_run:
        log.info("[DRY-RUN] item %d → source_name=%r  source_type=%r", item_id, source_name, source_type)
        return
    conn.execute(
        "UPDATE items SET source_name = ?, source_type = ? WHERE item_id = ?",
        (source_name, source_type, item_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill item source data from Wowhead TBC into tbc_items.db"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch and parse but do NOT write to the database",
    )
    parser.add_argument(
        "--limit", type=int, default=None, metavar="N",
        help="Process at most N items (useful for testing)",
    )
    parser.add_argument(
        "--item", type=int, default=None, metavar="ITEM_ID",
        help="Process a single item by ID (ignores source_name filter)",
    )
    parser.add_argument(
        "--db", default=DB_PATH, metavar="PATH",
        help=f"Path to SQLite DB (default: {DB_PATH})",
    )
    parser.add_argument(
        "--delay", type=float, default=RATE_LIMIT_SECONDS, metavar="SEC",
        help=f"Seconds between requests (default: {RATE_LIMIT_SECONDS})",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable DEBUG logging",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if not os.path.exists(args.db):
        log.error("Database not found: %s", args.db)
        sys.exit(1)

    conn = sqlite3.connect(args.db)

    # Single-item mode
    if args.item is not None:
        cur = conn.execute("SELECT item_id, name FROM items WHERE item_id = ?", (args.item,))
        row = cur.fetchone()
        if not row:
            log.error("item %d not found in DB", args.item)
            sys.exit(1)
        items = [row]
        log.info("Single-item mode: %d (%s)", row[0], row[1])
    else:
        items = fetch_items_needing_source(conn, limit=args.limit)
        log.info("Found %d items with empty source_name (phase >= 1)", len(items))

    if not items:
        log.info("Nothing to do.")
        conn.close()
        return

    updated = 0
    skipped = 0
    errors  = 0

    for i, (item_id, name) in enumerate(items, 1):
        log.info("[%d/%d] item %d — %s", i, len(items), item_id, name)

        try:
            source_name, source_type = get_item_source(item_id)
        except Exception as exc:  # noqa: BLE001
            log.error("item %d: unhandled exception: %s", item_id, exc)
            errors += 1
            time.sleep(args.delay)
            continue

        if source_name is None and source_type is None:
            log.info("  → no source data found — skipping")
            skipped += 1
        else:
            sn = source_name or ""
            st = source_type or ""
            log.info("  → %r / %r", sn, st)
            update_item_source(conn, item_id, sn, st, dry_run=args.dry_run)
            updated += 1

        # Rate limit
        if i < len(items):
            time.sleep(args.delay)

    conn.close()

    log.info(
        "Done. updated=%d  skipped=%d  errors=%d  dry_run=%s",
        updated, skipped, errors, args.dry_run,
    )


if __name__ == "__main__":
    main()
