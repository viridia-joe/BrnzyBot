#!/usr/bin/env python3
"""
Discord command: !gearprio <character> <raid>
Reports top 3 upgrades available from a specific raid.

Usage from OpenClaw skill dispatch:
  python3 gearprio.py Brnz Kara
  python3 gearprio.py Brnz Gruul
  python3 gearprio.py Brnz Mag
"""

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(__file__))
from bot_footer import FOOTER
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DB_PATH = os.path.expanduser("~/.openclaw/data/tbc_items.db")

DEFAULT_SERVER = "dreamscythe"
DEFAULT_REGION = "us"

KNOWN_CHARS = {
    "brnz": "destro_warlock",
}

RAID_ALIASES = {
    "kara": "Karazhan",
    "karazhan": "Karazhan",
    "gruul": "Gruul",
    "gruuls": "Gruul",
    "mag": "Magtheridon",
    "mags": "Magtheridon",
    "magtheridon": "Magtheridon",
    "ssc": "SSC",
    "serpentshrine": "SSC",
    "tk": "TK",
    "tempest": "TK",
    "eye": "TK",
    "hyjal": "Hyjal",
    "bt": "Black Temple",
    "blacktemple": "Black Temple",
    "za": "Zul'Aman",
    "zulaman": "Zul'Aman",
    "sunwell": "Sunwell",
    "swp": "Sunwell",
    "badges": "Badge",
}

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


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        raids = ", ".join(sorted(set(RAID_ALIASES.values())))
        print(f"Usage: /gearprio <character> <raid>\nRaids: {raids}")
        return

    name = args[0]
    raid_input = args[1].lower()
    server = args[2] if len(args) > 2 else DEFAULT_SERVER
    spec = args[3] if len(args) > 3 else KNOWN_CHARS.get(name.lower(), "destro_warlock")

    raid_name = RAID_ALIASES.get(raid_input)
    if not raid_name:
        raids = ", ".join(sorted(set(RAID_ALIASES.values())))
        print(f"Unknown raid: {args[1]}\nAvailable: {raids}")
        return

    # Load weights
    weight_file = os.path.expanduser(f"~/.openclaw/data/weights/{spec}.json")
    if not os.path.exists(weight_file):
        print(f"Unknown spec: {spec}")
        return

    with open(weight_file) as f:
        spec_data = json.load(f)
    weights = spec_data["weights"]
    armor_types = spec_data.get("armor_types", [])

    # Get current gear from WCL
    token = get_wcl_token()

    result = wcl_query(token, f'''{{
        characterData {{
            character(name: "{name}", serverSlug: "{server}", serverRegion: "{DEFAULT_REGION}") {{
                classID recentReports(limit: 1) {{ data {{ code }} }}
            }}
        }}
    }}''')

    char = result["data"]["characterData"]["character"]
    if not char or not char["recentReports"]["data"]:
        print(f"No WCL data for {name} on {server}")
        return

    code = char["recentReports"]["data"][0]["code"]

    # Find actor
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
        print(f"Could not find {name} in report {code}")
        return

    # Get gear
    result = wcl_query(token, f'''{{
        reportData {{ report(code: "{code}") {{
            events(sourceID: {actor_id}, dataType: CombatantInfo, startTime: 0, endTime: 999999999999) {{ data }}
        }} }}
    }}''')

    events = result["data"]["reportData"]["report"]["events"]["data"]
    if not events:
        print(f"No gear data for {name}")
        return

    event = events[-1]
    db = sqlite3.connect(DB_PATH)
    c = db.cursor()

    # Build current gear EP map by slot
    current_gear = {}
    for i, gear_item in enumerate(event["gear"]):
        item_id = gear_item.get("id", 0)
        slot = WCL_SLOT_MAP.get(i)
        if not slot or item_id == 0 or slot == "Shirt":
            continue

        c.execute("SELECT name, stats FROM items WHERE item_id = ?", (item_id,))
        row = c.fetchone()
        if row:
            stats = json.loads(row[1])
            ep = sum(stats.get(k, 0) * v for k, v in weights.items())
            current_gear[slot] = {"name": row[0], "ep": ep, "item_id": item_id}
        else:
            current_gear[slot] = {"name": f"Unknown ({item_id})", "ep": 0, "item_id": item_id}

    # Find all items from this raid that are upgrades
    # Match raid name against source_name in the database
    upgrades = []

    for slot, current in current_gear.items():
        # Query items from this raid for this slot
        class_name = spec_data.get("class", "")
        c.execute(
            "SELECT item_id, name, stats, source_name, quality, class_restriction, armor_type FROM items WHERE slot = ? AND source_name LIKE ? AND quality IN ('Epic', 'Rare')",
            (slot, f"%{raid_name}%"),
        )

        for row in c.fetchall():
            # Filter by class restriction
            class_restriction = json.loads(row[5]) if row[5] else []
            if class_restriction and class_name and class_name not in class_restriction:
                continue

            # Check armor type compatibility
            item_armor = row[6] or ""
            if armor_types and slot not in ("Neck", "Back", "Ring", "Trinket", "Main Hand", "Off Hand", "Wand"):
                if item_armor and item_armor not in armor_types:
                    continue

            item_stats = json.loads(row[2])
            ep = sum(item_stats.get(k, 0) * v for k, v in weights.items())
            gain = ep - current["ep"]

            if gain > 0:

                upgrades.append({
                    "slot": slot,
                    "name": row[1],
                    "ep": ep,
                    "gain": gain,
                    "source": row[3],
                    "replacing": current["name"],
                    "replacing_ep": current["ep"],
                })

    upgrades.sort(key=lambda x: -x["gain"])

    # Format output
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    lines = [
        f"**{name}** — Top upgrades from **{raid_name}** ({spec_data['spec']})",
        "",
    ]

    if not upgrades:
        lines.append(f"No upgrades available from {raid_name} for your current gear. You've outgeared it for this spec.")
    else:
        for i, up in enumerate(upgrades[:3], 1):
            lines.append(f"**{i}. {up['name']}** ({up['slot']})")
            lines.append(f"   EP {up['ep']:.0f} (+{up['gain']:.0f}) — replaces {up['replacing']} (EP {up['replacing_ep']:.0f})")
            lines.append(f"   Source: {up['source']}")
            lines.append("")

        if len(upgrades) > 3:
            lines.append(f"*+{len(upgrades) - 3} more upgrades available*")

    lines.append(f"\n_{now}_")
    db.close()
    lines.append(FOOTER)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
