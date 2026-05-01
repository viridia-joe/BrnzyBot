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

_REPO_ROOT       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH          = os.path.expanduser("~/.openclaw/data/tbc_items.db")
WEIGHTS_DIR      = os.path.join(_REPO_ROOT, "data", "weights")
WORKSPACE        = os.path.expanduser("~/.openclaw/workspace")
SET_BONUSES_PATH = os.path.join(_REPO_ROOT, "data", "set_bonuses.json")
OUTPUT           = os.path.join(WORKSPACE, "GEAR-STATUS.md")

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


def load_set_bonuses():
    """Load set bonus definitions. Returns {} if file missing."""
    if not os.path.exists(SET_BONUSES_PATH):
        return {}
    with open(SET_BONUSES_PATH) as f:
        return json.load(f)


def compute_ep(stats_dict, weights):
    """Compute equivalency points for an item's stats."""
    return sum(stats_dict.get(k, 0) * v for k, v in weights.items())


def compute_set_bonus_cost(current_set_name, current_set_count, set_bonuses):
    """
    Return the EP cost of losing one piece from a set (i.e. breaking a bonus tier).

    When a character replaces a set piece with a non-set item, the set count drops
    by 1. If that crosses a bonus threshold (e.g. 2→1 loses the 2-piece bonus),
    the EP value of that bonus is the real cost of the swap.

    Returns 0 if no bonus is lost.
    """
    if not current_set_name or current_set_name not in set_bonuses:
        return 0.0

    bonuses = set_bonuses[current_set_name]
    ep_at_current = 0.0
    ep_at_minus_one = 0.0

    for threshold_str, bonus in bonuses.items():
        if not threshold_str.isdigit():
            continue
        threshold = int(threshold_str)
        ep_value = bonus.get("ep", 0)
        if threshold <= current_set_count:
            ep_at_current += ep_value
        if threshold <= current_set_count - 1:
            ep_at_minus_one += ep_value

    return ep_at_current - ep_at_minus_one


def get_upgrades(db_conn, slot, current_ep, phase, weights, armor_types=None, class_name=None,
                 limit=5, current_set_name=None, current_set_count=0, set_bonuses=None):
    """Find top upgrades for a slot from the database."""
    c = db_conn.cursor()

    query = "SELECT item_id, name, stats, quality, ilvl, source_type, source_name, drop_rate, effort_score, set_name, class_restriction FROM items WHERE slot = ? AND phase <= ? AND quality IN ('Epic', 'Rare')"
    params = [slot, phase]

    if armor_types and slot not in ("Neck", "Back", "Ring", "Trinket"):
        placeholders = ",".join("?" * len(armor_types))
        # Include items with no armor type (accessories) too
        query += f" AND (armor_type IN ({placeholders}) OR armor_type = '')"
        params.extend(armor_types)

    c.execute(query, params)

    candidates = []
    for row in c.fetchall():
        # Filter by class restriction
        class_restriction = json.loads(row[10]) if row[10] else []
        if class_restriction and class_name and class_name not in class_restriction:
            continue

        stats = json.loads(row[2])
        ep = compute_ep(stats, weights)
        candidate_set = row[9] or ""

        # Net gain accounts for set bonus EP lost when breaking the current set,
        # unless the replacement is from the same set (no bonus lost).
        set_bonus_cost = 0.0
        if current_set_name and candidate_set != current_set_name and set_bonuses:
            set_bonus_cost = compute_set_bonus_cost(
                current_set_name, current_set_count, set_bonuses
            )

        gain = ep - current_ep - set_bonus_cost

        if gain > 0:
            candidates.append({
                "item_id": row[0],
                "name": row[1],
                "ep": ep,
                "gain": gain,
                "set_bonus_cost": round(set_bonus_cost, 1),
                "quality": row[3],
                "ilvl": row[4],
                "source_type": row[5] or "Unknown",
                "source_name": row[6] or "",
                "drop_rate": row[7] or 0,
                "effort_score": row[8] or EFFORT_SCORES.get(row[5], 5.0),
                "set_name": candidate_set,
            })

    # Sort by EP gain (later we can factor in effort)
    candidates.sort(key=lambda x: -x["gain"])
    return candidates[:limit]


def format_output(characters, set_bonuses=None):
    """Build GEAR-STATUS.md."""
    set_bonuses = set_bonuses or {}
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
        "**IMPORTANT — Set bonuses:** The Set Bonus Reference section below lists every set bonus",
        "with its actual effect and EP value. NEVER state set bonus effects that are not in that",
        "section. If an item is not shown as part of a named set, it has no set bonus.",
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

            set_tag = f" [{gear_entry['set_name']}]" if gear_entry.get("set_name") else ""
            lines.append(f"**{slot}:** {item_name}{set_tag} (EP {current_ep:.1f})")

            if upgrades:
                for up in upgrades:
                    source_info = up["source_name"] if up["source_name"] else up["source_type"]
                    effort_tag = ""
                    if up["source_type"] == "World Boss":
                        effort_tag = " [WORLD BOSS - very rare]"
                    set_cost_tag = ""
                    if up.get("set_bonus_cost", 0) > 0:
                        set_cost_tag = f" [breaks set, -{up['set_bonus_cost']:.0f} EP bonus]"
                    lines.append(f"  - {up['name']} (EP {up['ep']:.1f}, net +{up['gain']:.0f}){set_cost_tag} — {source_info}{effort_tag}")

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

        # Set Bonus Reference — ground truth, derived from set_bonuses.json.
        # Lists every set worn by this character with actual effects.
        # The model must use ONLY these values when answering set bonus questions.
        worn_sets: dict[str, int] = {}
        for g in char.get("gear", []):
            sn = g.get("set_name", "")
            if sn:
                worn_sets[sn] = worn_sets.get(sn, 0) + 1

        if worn_sets:
            lines.append("### Set Bonus Reference")
            lines.append("")
            lines.append("These are the ONLY set bonuses that exist for this character's current gear.")
            lines.append("Do not invent or recall set bonus effects from memory — use only what is listed here.")
            lines.append("")
            for sn, count in sorted(worn_sets.items()):
                if sn not in set_bonuses:
                    lines.append(f"**{sn}** ({count}/{count} equipped) — No bonus data on file.")
                    lines.append("")
                    continue
                bonuses_def = set_bonuses[sn]
                all_thresholds = sorted(
                    int(k) for k in bonuses_def if k.isdigit()
                )
                lines.append(f"**{sn}** — {count} piece(s) equipped")
                for t in all_thresholds:
                    b = bonuses_def[str(t)]
                    active = "✓ ACTIVE" if count >= t else f"✗ need {t - count} more"
                    lines.append(f"  - {t}-piece: {b['desc']} ({b['ep']:.0f} EP) [{active}]")
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

    # Load set bonuses for net gain calculations
    set_bonuses = load_set_bonuses()

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

        # Get item stats and set membership from DB
        c = db_conn.cursor()
        c.execute("SELECT stats, set_name FROM items WHERE item_id = ?", (item_id,))
        row = c.fetchone()
        if row:
            stats = json.loads(row[0])
            item_set_name = row[1] or ""
        else:
            stats = {}
            item_set_name = ""

        current_ep = compute_ep(stats, weights)

        # Count how many pieces of this set the character currently wears.
        # We count across already-processed slots — this loop builds gear_list
        # in WCL slot order, so we only have a partial count here. We do a
        # second pass below to get accurate counts, so pass 0 for now and
        # fix up after the loop.
        upgrades = get_upgrades(
            db_conn, slot, current_ep, phase, weights, armor_types, class_name,
            current_set_name=item_set_name,
            current_set_count=0,       # fixed up in second pass below
            set_bonuses=set_bonuses,
        )

        gear_list.append({
            "slot": slot,
            "name": item_name,
            "item_id": item_id,
            "ep": current_ep,
            "set_name": item_set_name,
            "upgrades": upgrades,
        })

    # Second pass: compute accurate set piece counts and re-run upgrades
    # for any slot occupied by a set item.
    set_counts: dict[str, int] = {}
    for entry in gear_list:
        if entry["set_name"]:
            set_counts[entry["set_name"]] = set_counts.get(entry["set_name"], 0) + 1

    for entry in gear_list:
        sn = entry["set_name"]
        if sn and set_counts.get(sn, 0) > 1:
            # Re-run with accurate count — upgrades may now correctly show set cost
            c = db_conn.cursor()
            c.execute("SELECT slot FROM items WHERE item_id = ?", (entry["item_id"],))
            slot_row = c.fetchone()
            if slot_row:
                entry["upgrades"] = get_upgrades(
                    db_conn, entry["slot"], entry["ep"], phase, weights,
                    armor_types, class_name,
                    current_set_name=sn,
                    current_set_count=set_counts[sn],
                    set_bonuses=set_bonuses,
                )

    # Build output
    characters = [{
        "name": args.name,
        "spec_desc": spec_desc,
        "report": report_info,
        "combat_stats": {k: event.get(k, 0) for k in ["hitSpell", "critSpell", "hasteSpell"]},
        "gear": gear_list,
    }]

    content = format_output(characters, set_bonuses=set_bonuses)
    with open(OUTPUT, "w") as f:
        f.write(content)

    print(f"Written to {OUTPUT}")
    db_conn.close()


if __name__ == "__main__":
    main()
