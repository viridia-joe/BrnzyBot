#!/usr/bin/env python3
"""
Compute gear upgrades for a character using the local item database.

Usage:
  python3 compute-upgrades.py --name Brnz --server dreamscythe --spec destro_warlock
  python3 compute-upgrades.py --name Brnz --server dreamscythe --spec destro_warlock --phase 1

Reads:
  ~/.openclaw/data/tbc_items.db (item database)
  ~/.openclaw/data/weights/<spec>.json (stat weights)
  WCL API for current gear (env: WCL_CLIENT_ID, WCL_CLIENT_SECRET)

Writes:
  ~/.openclaw/workspace/GEAR-STATUS.md
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DB_PATH = os.path.expanduser("~/.openclaw/data/tbc_items.db")
WEIGHTS_DIR = os.path.expanduser("~/.openclaw/data/weights")
WORKSPACE = os.path.expanduser("~/.openclaw/workspace")
OUTPUT = os.path.join(WORKSPACE, "GEAR-STATUS.md")

# Effort scores by source type
EFFORT_SCORES = {
    "Quest": 1.0,
    "Reputation": 2.0,
    "Badge": 2.5,
    "Crafted": 3.0,
    "Heroic Dungeon": 3.0,
    "Normal Dungeon": 2.0,
    "10-man Raid": 5.0,
    "25-man Raid": 6.0,
    "World Boss": 9.0,
    "Arena": 6.0,
    "PvP": 4.0,
    "Unknown": 5.0,
}

# WCL slot index → slot name
WCL_SLOT_MAP = {
    0: "Head", 1: "Neck", 2: "Shoulder", 3: "Shirt",
    4: "Chest", 5: "Waist", 6: "Legs", 7: "Feet",
    8: "Wrist", 9: "Hands", 10: "Ring", 11: "Ring",
    12: "Trinket", 13: "Trinket", 14: "Back",
    15: "Main Hand", 16: "Off Hand", 17: "Wand",
}


def http_post(url, data=None, json_data=None, headers=None):
    hdrs = headers or {}
    if json_data is not None:
        body = json.dumps(json_data).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    elif data is not None:
        body = urlencode(data).encode("utf-8")
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    else:
        body = b""
    req = Request(url, data=body, headers=hdrs, method="POST")
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_wcl_token():
    return http_post(
        "https://www.warcraftlogs.com/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": os.environ["WCL_CLIENT_ID"],
            "client_secret": os.environ["WCL_CLIENT_SECRET"],
        },
    )["access_token"]


def wcl_query(token, query):
    return http_post(
        "https://classic.warcraftlogs.com/api/v2/client",
        json_data={"query": query},
        headers={"Authorization": f"Bearer {token}"},
    )


def get_character_gear(token, name, server, region="us"):
    """Get gear from most recent WCL report."""
    result = wcl_query(token, f'''{{
        characterData {{
            character(name: "{name}", serverSlug: "{server}", serverRegion: "{region}") {{
                classID recentReports(limit: 1) {{ data {{ code startTime }} }}
            }}
        }}
    }}''')

    char = result["data"]["characterData"]["character"]
    if not char or not char["recentReports"]["data"]:
        return None, None

    report = char["recentReports"]["data"][0]
    code = report["code"]
    report_time = report["startTime"]

    # Find actor ID
    result = wcl_query(token, f'''{{
        reportData {{ report(code: "{code}") {{
            masterData {{ actors(type: "Player") {{ id name }} }}
        }} }}
    }}''')

    actor_id = None
    for actor in result["data"]["reportData"]["report"]["masterData"]["actors"]:
        if actor["name"] == name:
            actor_id = actor["id"]
            break

    if not actor_id:
        return None, None

    # Get gear
    result = wcl_query(token, f'''{{
        reportData {{ report(code: "{code}") {{
            events(sourceID: {actor_id}, dataType: CombatantInfo, startTime: 0, endTime: 999999999999) {{ data }}
        }} }}
    }}''')

    events = result["data"]["reportData"]["report"]["events"]["data"]
    if not events:
        return None, None

    return events[-1], {"code": code, "time": report_time}


def resolve_item_name(item_id, db_conn):
    """Look up item name from local DB. No external calls."""
    c = db_conn.cursor()
    c.execute("SELECT name FROM items WHERE item_id = ?", (item_id,))
    row = c.fetchone()
    return row[0] if row else f"Unknown ({item_id})"


def compute_ep(stats_dict, weights):
    """Compute equivalency points for an item's stats."""
    return sum(stats_dict.get(k, 0) * v for k, v in weights.items())


def get_upgrades(db_conn, slot, current_ep, phase, weights, armor_types=None, class_name=None, limit=5):
    """Find top upgrades for a slot from the database."""
    c = db_conn.cursor()

    query = "SELECT item_id, name, stats, quality, ilvl, source_type, source_name, drop_rate, effort_score, set_name FROM items WHERE slot = ? AND phase <= ? AND quality IN ('Epic', 'Rare')"
    params = [slot, phase]

    if armor_types and slot not in ("Neck", "Back", "Ring", "Trinket"):
        placeholders = ",".join("?" * len(armor_types))
        # Include items with no armor type (accessories) too
        query += f" AND (armor_type IN ({placeholders}) OR armor_type = '')"
        params.extend(armor_types)

    c.execute(query, params)

    candidates = []
    for row in c.fetchall():
        stats = json.loads(row[2])
        ep = compute_ep(stats, weights)
        gain = ep - current_ep

        if gain > 0:
            candidates.append({
                "item_id": row[0],
                "name": row[1],
                "ep": ep,
                "gain": gain,
                "quality": row[3],
                "ilvl": row[4],
                "source_type": row[5] or "Unknown",
                "source_name": row[6] or "",
                "drop_rate": row[7] or 0,
                "effort_score": row[8] or EFFORT_SCORES.get(row[5], 5.0),
                "set_name": row[9] or "",
            })

    # Sort by EP gain (later we can factor in effort)
    candidates.sort(key=lambda x: -x["gain"])
    return candidates[:limit]


def format_output(characters):
    """Build GEAR-STATUS.md."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Gear Status — Joe's Characters",
        "",
        f"**Last refreshed:** {now}",
        "**Source:** WCL gear + local item database (WowSims) + computed EP values",
        "",
        "Pre-built upgrade guide. Read this to answer gear questions — no external fetches needed.",
        "If this file is more than 24 hours old, run the refresh:",
        "`exec WCL_CLIENT_ID=$WCL_CLIENT_ID WCL_CLIENT_SECRET=$WCL_CLIENT_SECRET python3 ~/.openclaw/scripts/compute-upgrades.py --name Brnz --server dreamscythe --spec destro_warlock --phase 1`",
        "",
    ]

    for char in characters:
        lines.append("---")
        lines.append("")
        lines.append(f"## {char['name']} — {char['spec_desc']}")
        lines.append("")

        if char.get("report"):
            report_date = datetime.fromtimestamp(char["report"]["time"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            lines.append(f"Most recent log: [{char['report']['code']}](https://classic.warcraftlogs.com/reports/{char['report']['code']}) ({report_date})")

        if char.get("combat_stats"):
            s = char["combat_stats"]
            lines.append(f"Logged stats: {s.get('hitSpell', '?')} spell hit, {s.get('critSpell', '?')} spell crit, {s.get('hasteSpell', '?')} spell haste")

        lines.append("")
        lines.append("### Current Gear & Upgrades")
        lines.append("")

        weaknesses = []

        for gear_entry in char.get("gear", []):
            slot = gear_entry["slot"]
            item_name = gear_entry["name"]
            current_ep = gear_entry["ep"]
            upgrades = gear_entry["upgrades"]

            lines.append(f"**{slot}:** {item_name} (EP {current_ep:.1f})")

            if upgrades:
                for up in upgrades:
                    source_info = up["source_name"] if up["source_name"] else up["source_type"]
                    effort_tag = ""
                    if up["source_type"] == "World Boss":
                        effort_tag = " [WORLD BOSS - very rare]"
                    lines.append(f"  - {up['name']} (EP {up['ep']:.1f}, +{up['gain']:.0f}) — {source_info}{effort_tag}")

                best = upgrades[0]
                if best["gain"] > 10:
                    weaknesses.append((slot, item_name, current_ep, best))
            else:
                lines.append(f"  - No upgrades in current phase")

            lines.append("")

        if weaknesses:
            weaknesses.sort(key=lambda x: -x[3]["gain"])
            lines.append("### Biggest Weaknesses (largest EP gains)")
            lines.append("")
            for i, (slot, name, ep, upgrade) in enumerate(weaknesses[:5], 1):
                source = upgrade["source_name"] if upgrade["source_name"] else upgrade["source_type"]
                lines.append(f"{i}. **{slot}** — {name} → {upgrade['name']} (+{upgrade['gain']:.0f} EP) — {source}")
            lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Compute TBC gear upgrades")
    parser.add_argument("--name", required=True, help="Character name")
    parser.add_argument("--server", required=True, help="Server slug")
    parser.add_argument("--spec", required=True, help="Spec weight file name (without .json)")
    parser.add_argument("--phase", type=int, default=None, help="Max phase (default: read from PHASE.md)")
    parser.add_argument("--region", default="us", help="Server region")
    args = parser.parse_args()

    # Load phase from PHASE.md if not specified
    phase = args.phase
    if phase is None:
        phase_file = os.path.join(WORKSPACE, "PHASE.md")
        if os.path.exists(phase_file):
            with open(phase_file) as f:
                import re
                m = re.search(r"Phase (\d+)", f.read())
                phase = int(m.group(1)) if m else 1
        else:
            phase = 1
    print(f"Using phase: {phase}")

    # Load spec weights
    weight_file = os.path.join(WEIGHTS_DIR, f"{args.spec}.json")
    if not os.path.exists(weight_file):
        print(f"ERROR: Weight file not found: {weight_file}", file=sys.stderr)
        sys.exit(1)

    with open(weight_file) as f:
        spec_data = json.load(f)

    weights = spec_data["weights"]
    armor_types = spec_data.get("armor_types", [])
    spec_desc = spec_data.get("spec", args.spec)
    class_name = spec_data.get("class", "")

    # Connect to item database
    if not os.path.exists(DB_PATH):
        print(f"ERROR: Item database not found: {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    db_conn = sqlite3.connect(DB_PATH)

    # Get current gear from WCL
    print(f"Fetching gear for {args.name}@{args.server}...")
    token = get_wcl_token()
    event, report_info = get_character_gear(token, args.name, args.server, args.region)

    if not event:
        print(f"ERROR: Could not fetch gear for {args.name}", file=sys.stderr)
        sys.exit(1)

    # Process each gear slot
    gear_list = []
    print(f"Processing {len(event['gear'])} gear slots...")

    for i, gear_item in enumerate(event["gear"]):
        item_id = gear_item.get("id", 0)
        slot = WCL_SLOT_MAP.get(i)

        if not slot or item_id == 0 or slot == "Shirt":
            continue

        # Resolve item name
        item_name = resolve_item_name(item_id, db_conn)

        # Get item stats from DB
        c = db_conn.cursor()
        c.execute("SELECT stats FROM items WHERE item_id = ?", (item_id,))
        row = c.fetchone()
        if row:
            stats = json.loads(row[0])
        else:
            stats = {}

        current_ep = compute_ep(stats, weights)

        # Find upgrades
        upgrades = get_upgrades(db_conn, slot, current_ep, phase, weights, armor_types, class_name)

        gear_list.append({
            "slot": slot,
            "name": item_name,
            "item_id": item_id,
            "ep": current_ep,
            "upgrades": upgrades,
        })

    # Build output
    characters = [{
        "name": args.name,
        "spec_desc": spec_desc,
        "report": report_info,
        "combat_stats": {k: event.get(k, 0) for k in ["hitSpell", "critSpell", "hasteSpell"]},
        "gear": gear_list,
    }]

    content = format_output(characters)
    with open(OUTPUT, "w") as f:
        f.write(content)

    print(f"Written to {OUTPUT}")
    db_conn.close()


if __name__ == "__main__":
    main()
