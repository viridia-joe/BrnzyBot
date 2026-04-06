#!/usr/bin/env python3
"""
!upgrade <character> <slot>

Show all available upgrades for a specific gear slot, ranked by EP.
Includes source, effort, and EP delta from current item.

Usage:
  python3 upgrade.py Brnz belt
  python3 upgrade.py Brnzy neck
  python3 upgrade.py Voidray bracers
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

sys.path.insert(0, os.path.dirname(__file__))
from bot_footer import FOOTER

DB_PATH = os.path.expanduser("~/.openclaw/data/tbc_items.db")
WEIGHTS_DIR = os.path.expanduser("~/.openclaw/data/weights")
GEMS_PATH = os.path.expanduser("~/.openclaw/data/gems.json")
TRINKET_EP_PATH = os.path.expanduser("~/.openclaw/data/trinket_ep.json")
BIS_EXCLUSIONS_PATH = os.path.expanduser("~/.openclaw/data/bis_exclusions.json")
CACHE_PATH = os.path.expanduser("~/.openclaw/data/gear_cache.json")
TIERS_PATH = os.path.expanduser("~/.openclaw/data/tiers.json")
DEFAULT_SERVER = "dreamscythe"

# Slot name aliases → canonical WCL slot name
SLOT_ALIASES = {
    # Head
    "head": "Head", "helm": "Head", "helmet": "Head",
    # Neck
    "neck": "Neck", "necklace": "Neck", "amulet": "Neck",
    # Shoulder
    "shoulder": "Shoulder", "shoulders": "Shoulder", "pauldrons": "Shoulder",
    # Back
    "back": "Back", "cloak": "Back", "cape": "Back",
    # Chest
    "chest": "Chest", "robe": "Chest", "chestpiece": "Chest",
    # Wrist
    "wrist": "Wrist", "wrists": "Wrist", "bracer": "Wrist", "bracers": "Wrist",
    # Hands
    "hands": "Hands", "gloves": "Hands", "gauntlets": "Hands",
    # Waist
    "waist": "Waist", "belt": "Waist",
    # Legs
    "legs": "Legs", "leggings": "Legs", "pants": "Legs",
    # Feet
    "feet": "Feet", "boots": "Feet",
    # Ring
    "ring": "Ring", "rings": "Ring", "finger": "Ring",
    # Trinket
    "trinket": "Trinket", "trinkets": "Trinket",
    # Main Hand
    "mainhand": "Main Hand", "mh": "Main Hand", "weapon": "Main Hand",
    # Off Hand
    "offhand": "Off Hand", "oh": "Off Hand", "shield": "Off Hand",
    # Wand / Ranged
    "wand": "Wand", "ranged": "Ranged", "gun": "Ranged", "bow": "Ranged",
    "totem": "Totem", "idol": "Idol", "libram": "Libram",
}

WCL_SLOT_MAP = {
    0: "Head", 1: "Neck", 2: "Shoulder", 3: "Shirt",
    4: "Chest", 5: "Waist", 6: "Legs", 7: "Feet",
    8: "Wrist", 9: "Hands", 10: "Ring", 11: "Ring",
    12: "Trinket", 13: "Trinket", 14: "Back",
    15: "Main Hand", 16: "Off Hand", 17: "Ranged",
}

SPEC_MAP = {
    "Warlock": {0: "affliction_warlock", 1: None, 2: "destro_warlock"},
    "Mage": {0: "arcane_mage", 1: "fire_mage", 2: "frost_mage"},
    "Priest": {0: "holy_priest", 1: "holy_priest", 2: "shadow_priest"},
    "Druid": {0: "balance_druid", 1: "feral_cat_druid", 2: "resto_druid"},
    "Hunter": {0: "bm_hunter", 1: "mm_hunter", 2: "survival_hunter"},
    "Shaman": {0: "ele_shaman", 1: "enh_shaman", 2: "resto_shaman"},
    "Rogue": {0: "assassination_rogue", 1: "combat_rogue", 2: None},
    "Warrior": {0: "arms_warrior", 1: "fury_warrior", 2: "prot_warrior"},
    "Paladin": {0: "holy_paladin", 1: "prot_paladin", 2: "ret_paladin"},
}

MELEE_SPECS = {
    "feral_cat_druid", "feral_bear_druid", "enh_shaman", "combat_rogue",
    "assassination_rogue", "fury_warrior", "arms_warrior", "prot_warrior",
    "ret_paladin", "prot_paladin", "bm_hunter", "mm_hunter", "survival_hunter",
}

CLASS_RANGED_SLOT = {
    "Warlock": "Wand", "Mage": "Wand", "Priest": "Wand",
    "Shaman": "Totem", "Druid": "Idol", "Paladin": "Libram",
    "Hunter": "Ranged", "Warrior": "Ranged", "Rogue": "Ranged",
}

GEM_PROFILE_MAP = {
    "destro_warlock": "caster", "affliction_warlock": "caster", "fire_destro_warlock": "caster",
    "fire_mage": "caster", "arcane_mage": "caster", "frost_mage": "caster",
    "shadow_priest": "caster", "ele_shaman": "caster", "balance_druid": "caster",
    "holy_priest": "healer", "resto_druid": "healer", "resto_shaman": "healer", "holy_paladin": "healer",
    "feral_bear_druid": "tank", "prot_warrior": "tank", "prot_paladin": "tank",
    "bm_hunter": "melee_phys", "mm_hunter": "melee_phys", "survival_hunter": "melee_phys",
    "combat_rogue": "melee_phys", "assassination_rogue": "melee_phys",
    "feral_cat_druid": "melee_phys", "enh_shaman": "melee_phys",
    "fury_warrior": "melee_str", "arms_warrior": "melee_str", "ret_paladin": "melee_str",
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
            "client_id": os.environ.get("WCL_CLIENT_ID", ""),
            "client_secret": os.environ.get("WCL_CLIENT_SECRET", ""),
        },
    )["access_token"]


def wcl_query(token, query):
    import time
    for attempt in range(3):
        try:
            return http_post(
                "https://classic.warcraftlogs.com/api/v2/client",
                json_data={"query": query},
                headers={"Authorization": f"Bearer {token}"},
            )
        except HTTPError as e:
            if e.code == 503 and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            raise


def load_json(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def get_cached_gear(name, server):
    cache = load_json(CACHE_PATH)
    key = f"{name.lower()}@{server.lower()}"
    entry = cache.get(key)
    if not entry:
        return None
    age_hours = (datetime.now(timezone.utc).timestamp() - entry.get("cached_at", 0)) / 3600
    if age_hours > 4:
        return None
    return entry


def save_gear_cache(name, server, event, report_code, report_time, class_name):
    cache = load_json(CACHE_PATH)
    key = f"{name.lower()}@{server.lower()}"
    cache[key] = {
        "cached_at": datetime.now(timezone.utc).timestamp(),
        "event": event, "report_code": report_code,
        "report_time": report_time, "class_name": class_name, "name": name,
    }
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f)


def fetch_from_wcl(name, server):
    token = get_wcl_token()

    result = wcl_query(token, f'''{{
        characterData {{
            character(name: "{name}", serverSlug: "{server}", serverRegion: "us") {{
                classID recentReports(limit: 1) {{ data {{ code startTime }} }}
            }}
        }}
    }}''')
    char = result["data"]["characterData"]["character"]
    if not char or not char["recentReports"]["data"]:
        return None, None, None, None

    code = char["recentReports"]["data"][0]["code"]
    report_time = char["recentReports"]["data"][0]["startTime"]

    result = wcl_query(token, f'''{{
        reportData {{ report(code: "{code}") {{
            masterData {{ actors(type: "Player") {{ id name subType }} }}
        }} }}
    }}''')

    actor_id = None
    class_name = "Unknown"
    for actor in result["data"]["reportData"]["report"]["masterData"]["actors"]:
        if actor["name"].lower() == name.lower():
            actor_id = actor["id"]
            class_name = actor.get("subType", "Unknown")
            name = actor["name"]
            break
    if not actor_id:
        return None, None, None, None

    result = wcl_query(token, f'''{{
        reportData {{ report(code: "{code}") {{
            events(sourceID: {actor_id}, dataType: CombatantInfo, startTime: 0, endTime: 999999999999) {{ data }}
        }} }}
    }}''')
    events = result["data"]["reportData"]["report"]["events"]["data"]
    if not events:
        return None, None, None, None

    return events[-1], class_name, code, report_time


def detect_spec(class_name, talents):
    if not talents or len(talents) < 3:
        return None
    points = [t.get("id", 0) for t in talents]
    max_tree = points.index(max(points))
    spec = SPEC_MAP.get(class_name, {}).get(max_tree)
    if class_name == "Warlock" and max_tree == 2:
        spec = "destro_warlock" if points[1] >= 21 else "fire_destro_warlock"
    return spec


def compute_gem_ep(sockets, socket_bonus, weights, gem_profile):
    if not sockets or not gem_profile:
        return 0
    gem_ep = 0
    for color in sockets:
        gem = gem_profile.get(color)
        if gem:
            if "stats" in gem:
                gem_ep += sum(gem["stats"].get(k, 0) * weights.get(k, 0) for k in gem["stats"])
            gem_ep += gem.get("bonusEP", 0)
    if socket_bonus:
        gem_ep += sum(socket_bonus.get(k, 0) * weights.get(k, 0) for k in socket_bonus)
    return gem_ep


def compute_item_ep(item_id, stats_json, sockets_json, bonus_json, weights, gem_profile, spec, trinket_data):
    stats = json.loads(stats_json) if isinstance(stats_json, str) else stats_json
    sockets = json.loads(sockets_json) if isinstance(sockets_json, str) else (sockets_json or [])
    bonus = json.loads(bonus_json) if isinstance(bonus_json, str) else (bonus_json or {})

    ep = sum(stats.get(k, 0) * v for k, v in weights.items())
    ep += compute_gem_ep(sockets, bonus, weights, gem_profile)

    # Trinket override
    trinket_entry = trinket_data.get(str(item_id))
    if trinket_entry and spec in trinket_entry:
        ep = trinket_entry[spec]

    return ep


def is_excluded(item_name, set_name, source_type, exclusions):
    for cat_key, cat in exclusions.items():
        if cat_key.startswith("_") or not isinstance(cat, dict):
            continue
        emoji = cat.get("emoji", "🚫")
        label = cat.get("label", cat_key)
        if source_type in cat.get("source_types", []):
            return True, emoji, label
        if set_name in cat.get("set_names", []):
            return True, emoji, label
        for pattern in cat.get("item_name_patterns", []):
            if pattern.lower() in item_name.lower():
                return True, emoji, label
    return False, None, None


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        slots = ", ".join(sorted(set(SLOT_ALIASES.keys())))
        print(f"**!upgrade** — Usage: `!upgrade <character> <slot>`\nSlots: {slots}")
        return

    name = args[0]
    slot_input = " ".join(args[1:]).lower().strip()
    server = DEFAULT_SERVER

    # Resolve slot alias
    target_slot = SLOT_ALIASES.get(slot_input)
    if not target_slot:
        # Try multi-word: "main hand", "off hand"
        target_slot = SLOT_ALIASES.get(slot_input.replace(" ", ""))
    if not target_slot:
        print(f"Unknown slot: **{slot_input}**\nTry: head, neck, shoulder, back, chest, wrist, hands, belt, legs, feet, ring, trinket, mh, oh, wand")
        return

    # Get character gear (cached or fresh)
    cached = get_cached_gear(name, server)
    if cached:
        event = cached["event"]
        class_name = cached["class_name"]
        name = cached["name"]
    else:
        try:
            event, class_name, code, report_time = fetch_from_wcl(name, server)
            if not event:
                print(f"**{name}** not found on WCL for **{server}**.")
                return
            save_gear_cache(name, server, event, code, report_time, class_name)
        except Exception as e:
            print(f"WCL error: {e}")
            return

    # Detect spec
    spec = detect_spec(class_name, event.get("talents", []))
    if not spec:
        print(f"Could not detect spec for **{name}** ({class_name}).")
        return

    # Load data files
    weight_file = os.path.join(WEIGHTS_DIR, f"{spec}.json")
    if not os.path.exists(weight_file):
        print(f"No weight file for spec: {spec}")
        return
    with open(weight_file) as f:
        spec_data = json.load(f)
    weights = spec_data["weights"]
    armor_types = spec_data.get("armor_types", [])
    class_filter = spec_data.get("class", "")

    gem_data = load_json(GEMS_PATH)
    gem_profile = gem_data.get(GEM_PROFILE_MAP.get(spec, "caster"), {})
    trinket_data = load_json(TRINKET_EP_PATH)
    exclusions = load_json(BIS_EXCLUSIONS_PATH)
    tiers = load_json(TIERS_PATH).get("tiers", [])

    # Read phase
    phase = 1
    phase_file = os.path.expanduser("~/.openclaw/workspace/PHASE.md")
    if os.path.exists(phase_file):
        import re
        with open(phase_file) as f:
            m = re.search(r"Phase (\d+)", f.read())
            if m:
                phase = int(m.group(1))

    # Resolve ranged slot per class
    if target_slot == "Ranged":
        target_slot = CLASS_RANGED_SLOT.get(class_name, "Ranged")
    if target_slot == "Wand" and class_name not in ("Warlock", "Mage", "Priest"):
        target_slot = CLASS_RANGED_SLOT.get(class_name, "Ranged")

    # Find current item in that slot
    db = sqlite3.connect(DB_PATH)
    current_items = []
    for i, gear_item in enumerate(event.get("gear", [])):
        wcl_slot = WCL_SLOT_MAP.get(i)
        if not wcl_slot:
            continue
        # Resolve ranged
        if wcl_slot == "Ranged":
            wcl_slot = CLASS_RANGED_SLOT.get(class_name, "Ranged")

        if wcl_slot != target_slot:
            continue

        item_id = gear_item.get("id", 0)
        if item_id == 0:
            continue

        c = db.cursor()
        c.execute("SELECT name, stats, sockets, socket_bonus FROM items WHERE item_id = ?", (item_id,))
        row = c.fetchone()
        if row:
            ep = compute_item_ep(item_id, row[1], row[2], row[3], weights, gem_profile, spec, trinket_data)
            current_items.append({"id": item_id, "name": row[0], "ep": ep})
        else:
            current_items.append({"id": item_id, "name": f"Unknown #{item_id}", "ep": 0})

    if not current_items:
        print(f"No **{target_slot}** item found on **{name}**.")
        db.close()
        return

    # Best current EP in this slot
    best_current = max(current_items, key=lambda x: x["ep"])
    current_ep = best_current["ep"]
    current_name = best_current["name"]

    # Query all upgrades for this slot
    db_slot = target_slot
    name_filter = None
    if target_slot in ("Totem", "Idol", "Libram"):
        db_slot = "Ranged"
        name_filter = target_slot

    c = db.cursor()
    query = "SELECT item_id, name, stats, quality, sockets, socket_bonus, source_type, source_name, set_name, class_restriction FROM items WHERE slot = ? AND phase <= ? AND quality IN ('Epic', 'Rare')"
    params = [db_slot, phase]

    if armor_types and target_slot not in ("Neck", "Back", "Ring", "Trinket", "Main Hand", "Off Hand", "One Hand", "Two-Hand", "Wand", "Ranged", "Relic", "Totem", "Idol", "Libram"):
        placeholders = ",".join("?" * len(armor_types))
        query += f" AND (armor_type IN ({placeholders}) OR armor_type = '')"
        params.extend(armor_types)

    c.execute(query, params)

    upgrades = []
    for row in c.fetchall():
        row_id, row_name = row[0], row[1]

        if name_filter and name_filter.lower() not in row_name.lower():
            continue

        # Class restriction
        cr = json.loads(row[9]) if row[9] else []
        if cr and class_filter and class_filter not in cr:
            continue

        # Skip current item
        if row_id in [ci["id"] for ci in current_items]:
            continue

        ep = compute_item_ep(row_id, row[2], row[4], row[5], weights, gem_profile, spec, trinket_data)
        gain = ep - current_ep

        if gain <= 0:
            continue

        source_type = row[6] or "Unknown"
        source_name = row[7] or ""
        set_name = row[8] or ""

        excluded, excl_emoji, excl_label = is_excluded(row_name, set_name, source_type, exclusions)

        upgrades.append({
            "name": row_name,
            "ep": ep,
            "gain": gain,
            "source_type": source_type,
            "source_name": source_name,
            "set_name": set_name,
            "excluded": excluded,
            "excl_emoji": excl_emoji or "",
            "excl_label": excl_label or "",
            "quality": row[3],
        })

    upgrades.sort(key=lambda x: -x["gain"])

    # Format output
    lines = []
    lines.append(f"**{name}** — {target_slot} upgrades ({spec_data['spec']})")
    lines.append(f"Current: **{current_name}** ({current_ep:.0f} EP)")
    lines.append("")

    if not upgrades:
        lines.append(f"No upgrades available in Phase {phase}. You're at BiS for this slot.")
    else:
        # Show top 10 obtainable, then up to 3 excluded
        obtainable = [u for u in upgrades if not u["excluded"]]
        excluded_list = [u for u in upgrades if u["excluded"]]

        for i, up in enumerate(obtainable[:10], 1):
            source = up["source_name"] if up["source_name"] else up["source_type"]
            set_tag = f" [{up['set_name']}]" if up["set_name"] else ""
            lines.append(f"**{i}. {up['name']}** ({up['ep']:.0f} EP, +{up['gain']:.0f})")
            lines.append(f"   {source}{set_tag}")

        if excluded_list:
            lines.append("")
            lines.append("*Also available (restricted):*")
            for up in excluded_list[:3]:
                source = up["source_name"] if up["source_name"] else up["source_type"]
                lines.append(f"{up['excl_emoji']} {up['name']} ({up['ep']:.0f} EP, +{up['gain']:.0f}) — {source} ({up['excl_label']})")

    lines.append(FOOTER)
    db.close()
    print("\n".join(lines))


if __name__ == "__main__":
    main()
