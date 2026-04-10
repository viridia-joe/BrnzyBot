#!/usr/bin/env python3
"""
enrich_item_sources.py — Backfill source_name / source_type using community dataset.

Data source: nexus-devs/wow-classic-items (GitHub)
  https://raw.githubusercontent.com/nexus-devs/wow-classic-items/master/data/json/data.json

Each item in that file has a "source" dict like:
  {"category": "Drop", "name": "Gruul the Dragonkiller", "zone": "Gruul's Lair"}
  {"category": "Badge", "name": "Badge of Justice"}
  {"category": "Vendor", "name": "G'eras"}
  {"category": "Crafted", "name": "Tailoring"}
  {"category": "Quest", "name": "..."}

Usage:
    # Download the data file first:
    curl -s -o /tmp/wow_items.json \\
        https://raw.githubusercontent.com/nexus-devs/wow-classic-items/master/data/json/data.json

    # Run enrichment (dry-run first):
    python3 enrich_item_sources.py --data /tmp/wow_items.json --dry-run

    # Live run:
    python3 enrich_item_sources.py --data /tmp/wow_items.json
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import json
import urllib.request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

DB_PATH        = os.path.expanduser("~/.openclaw/data/tbc_items.db")
DATA_URL       = "https://raw.githubusercontent.com/nexus-devs/wow-classic-items/master/data/json/data.json"
ZONES_URL      = "https://raw.githubusercontent.com/nexus-devs/wow-classic-items/master/data/json/zones.json"
DEFAULT_DATA   = "/tmp/wow_items.json"
DEFAULT_ZONES  = "/tmp/wow_zones.json"

# Badge-exchange quest name fragments — these are actually badge gear
BADGE_QUEST_FRAGMENTS = (
    "Covenant", "Etched in Sorrow", "Veteran's Valor", "Defender No More",
    "Champion No More", "Sage", "Restorer", "Sentinel's Medallion",
    "DEPRECATED", "Crusader",
)

# Map community dataset "category" values → our source_type labels
CATEGORY_MAP = {
    "Drop":         None,        # need zone to classify further
    "Boss":         None,        # same
    "Zone Drop":    "Drop",      # generic zone drop — zone is a numeric ID, skip name
    "Raid":         "Raid",
    "Dungeon":      "Dungeon",
    "Heroic":       "Heroic Dungeon",
    "Badge":        "Badge",
    "PvP":          "PvP",
    "Arena":        "Arena",
    "Crafted":      "Crafted",
    "Tailoring":    "Crafted",
    "Blacksmithing":"Crafted",
    "Engineering":  "Crafted",
    "Leatherworking":"Crafted",
    "Alchemy":      "Crafted",
    "Jewelcrafting":"Crafted",
    "Enchanting":   "Crafted",
    "Quest":        "Quest",
    "Vendor":       "Vendor",
    "Reputation":   "Vendor",
    "World Drop":   "Drop",
}

RAID_ZONES = {
    "Karazhan", "Gruul", "Magtheridon", "Serpentshrine Cavern",
    "The Eye", "Tempest Keep", "Hyjal", "Black Temple", "Sunwell",
    "Zul'Aman", "Zul'Gurub", "Molten Core", "Blackwing Lair",
    "Ahn'Qiraj", "Naxxramas",
}


def _is_badge_quest(source: dict) -> bool:
    """Detect Badge-of-Justice items that wowhead labels as Quest rewards."""
    quests = source.get("quests", [])
    if not quests:
        return False
    for q in quests:
        qname = q.get("name", "")
        for frag in BADGE_QUEST_FRAGMENTS:
            if frag.lower() in qname.lower():
                return True
    return False


def _classify(category, zone_name: str, zone_category: str = "") -> str:
    """Derive source_type from community category + resolved zone info."""
    category = str(category or "")
    mapped = CATEGORY_MAP.get(category)
    if mapped:
        return mapped

    # "Boss Drop" / "Drop" — decide by zone category or zone name
    cat_lower = zone_category.lower()
    if "raid" in cat_lower:
        return "Raid"
    if "heroic" in cat_lower:
        return "Heroic Dungeon"
    if "dungeon" in cat_lower:
        return "Dungeon"

    if zone_name:
        z_lower = zone_name.lower()
        for raid in RAID_ZONES:
            if raid.lower() in z_lower:
                return "Raid"
        if "heroic" in z_lower:
            return "Heroic Dungeon"
        return "Dungeon"

    return "Drop"


def _build_source_name(source: dict, zone_map: dict) -> str:
    category = str(source.get("category") or "")

    # Badge-exchange quests disguised as Quest rewards
    if category == "Quest" and _is_badge_quest(source):
        return "Badge of Justice"

    # Zone drops — zone is a numeric ID, use "World Drop"
    if category == "Zone Drop":
        return "World Drop"

    name     = str(source.get("name") or "").strip()
    raw_zone = source.get("zone") or ""

    # Resolve numeric zone ID → zone name
    if isinstance(raw_zone, int):
        zone = zone_map.get(raw_zone, ("",))[0]
    else:
        zone = str(raw_zone).strip()

    if category in ("Badge",):
        return "Badge of Justice"
    if category == "Quest":
        return f"Quest: {name}" if name else "Quest"
    if category in ("Vendor", "Reputation"):
        return zone or name or "Vendor"
    if category in ("Crafted", "Tailoring", "Blacksmithing", "Engineering",
                    "Leatherworking", "Alchemy", "Jewelcrafting", "Enchanting"):
        return name or category

    # Boss Drop / Drop — "Zone - Boss" or just "Zone"
    if zone and name and name.lower() != zone.lower():
        return f"{zone} - {name}"
    return zone or name or ""


def _download_file(url: str, path: str, min_size: int = 0) -> None:
    """Download url → path, skip if already large enough."""
    if os.path.exists(path) and os.path.getsize(path) >= min_size:
        log.info("%s already present (%d bytes) — skipping", path, os.path.getsize(path))
        return
    log.info("Downloading %s …", url)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    with open(path, "wb") as f:
        f.write(data)
    log.info("Saved %d bytes → %s", len(data), path)


def download_data(path: str) -> None:
    _download_file(DATA_URL, path, min_size=30_000_000)


def load_zone_map(path: str) -> dict[int, tuple[str, str]]:
    """Return {zone_id: (zone_name, category)} from zones.json."""
    if not os.path.exists(path):
        _download_file(ZONES_URL, path, min_size=0)
    with open(path, encoding="utf-8") as f:
        zones = json.load(f)
    return {z["id"]: (z["name"], z.get("category", "")) for z in zones if "id" in z}


def load_community_data(path: str) -> dict[int, dict]:
    """Load and index community data by item_id."""
    log.info("Loading community item data from %s …", path)
    with open(path, encoding="utf-8") as f:
        items = json.load(f)
    log.info("Loaded %d items from community dataset", len(items))
    return {item["itemId"]: item for item in items if "itemId" in item}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich tbc_items.db source data from community dataset"
    )
    parser.add_argument("--db",      default=DB_PATH,      help="SQLite DB path")
    parser.add_argument("--data",    default=DEFAULT_DATA, help="Community JSON data file path")
    parser.add_argument("--download", action="store_true", help="Download data file first")
    parser.add_argument("--dry-run", action="store_true",  help="Print changes, no DB writes")
    parser.add_argument("--overwrite", action="store_true", help="Also overwrite existing source_name values")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.download:
        download_data(args.data)

    if not os.path.exists(args.data):
        log.error("Data file not found: %s — run with --download to fetch it", args.data)
        import sys; sys.exit(1)

    zone_map  = load_zone_map(DEFAULT_ZONES)
    log.info("Loaded %d zone definitions", len(zone_map))
    community = load_community_data(args.data)

    conn = sqlite3.connect(args.db)

    if args.overwrite:
        cur = conn.execute("SELECT item_id, name FROM items WHERE phase >= 1")
    else:
        cur = conn.execute(
            "SELECT item_id, name FROM items WHERE phase >= 1 "
            "AND (source_name IS NULL OR source_name = '')"
        )
    db_items = cur.fetchall()
    log.info("DB items needing source: %d", len(db_items))

    updated = skipped = 0
    for item_id, name in db_items:
        comm = community.get(item_id)
        if not comm:
            log.debug("item %d (%s): not in community dataset", item_id, name)
            skipped += 1
            continue

        source = comm.get("source")
        if not source or not isinstance(source, dict):
            # source can be an int (source type code) or missing — not useful without zone/name
            log.debug("item %d (%s): source not a dict (%r)", item_id, name, source)
            skipped += 1
            continue

        # Resolve numeric zone → name + category for classification
        raw_zone = source.get("zone") or ""
        if isinstance(raw_zone, int):
            zone_name, zone_cat = zone_map.get(raw_zone, ("", ""))
        else:
            zone_name, zone_cat = str(raw_zone), ""

        # Badge-exchange quests
        if source.get("category") == "Quest" and _is_badge_quest(source):
            source_name = "Badge of Justice"
            source_type = "Badge"
        else:
            source_name = _build_source_name(source, zone_map)
            source_type = _classify(source.get("category", ""), zone_name, zone_cat)

        if not source_name and not source_type:
            skipped += 1
            continue

        if args.dry_run:
            log.info("[DRY] %d %-45s → %r / %r", item_id, name[:44], source_name, source_type)
        else:
            conn.execute(
                "UPDATE items SET source_name=?, source_type=? WHERE item_id=?",
                (source_name, source_type, item_id),
            )
            log.debug("Updated %d (%s): %r / %r", item_id, name, source_name, source_type)
        updated += 1

    if not args.dry_run:
        conn.commit()
    conn.close()

    log.info("Done. updated=%d  skipped=%d  dry_run=%s", updated, skipped, args.dry_run)


if __name__ == "__main__":
    main()
