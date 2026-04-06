#!/usr/bin/env python3
"""
!gearcheck <character> [server]

Looks up a character on Warcraft Logs, auto-detects spec from talents,
reports current gear with EP values.

Every step is logged in the output so the user can see what happened.
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
CACHE_PATH = os.path.expanduser("~/.openclaw/data/gear_cache.json")
WEIGHTS_DIR = os.path.expanduser("~/.openclaw/data/weights")
GEMS_PATH = os.path.expanduser("~/.openclaw/data/gems.json")
SET_BONUSES_PATH = os.path.expanduser("~/.openclaw/data/set_bonuses.json")
TRINKET_EP_PATH = os.path.expanduser("~/.openclaw/data/trinket_ep.json")
TIERS_PATH = os.path.expanduser("~/.openclaw/data/tiers.json")
BIS_EXCLUSIONS_PATH = os.path.expanduser("~/.openclaw/data/bis_exclusions.json")
TANK_THRESHOLDS_PATH = os.path.expanduser("~/.openclaw/data/tank_thresholds.json")
TANK_SPECS = {"prot_warrior", "prot_paladin", "feral_bear_druid"}
DEFAULT_SERVER = "dreamscythe"
DEFAULT_REGION = "us"

WCL_SLOT_MAP = {
    0: "Head", 1: "Neck", 2: "Shoulder", 3: "Shirt",
    4: "Chest", 5: "Waist", 6: "Legs", 7: "Feet",
    8: "Wrist", 9: "Hands", 10: "Ring", 11: "Ring",
    12: "Trinket", 13: "Trinket", 14: "Back",
    15: "Main Hand", 16: "Off Hand", 17: "Ranged",  # Resolved per-class below
}

# Class → ranged slot type and DB slot for BiS lookup
# WCL position 17 is: Wand (casters), Ranged weapon (hunters/warriors/rogues),
# Totem (shamans), Idol (druids), Libram (paladins)
CLASS_RANGED_SLOT = {
    "Warlock": ("Wand", "Wand"),
    "Mage": ("Wand", "Wand"),
    "Priest": ("Wand", "Wand"),
    "Shaman": ("Totem", "Ranged"),
    "Druid": ("Idol", "Ranged"),
    "Paladin": ("Libram", "Ranged"),
    "Hunter": ("Ranged", "Ranged"),
    "Warrior": ("Ranged", "Ranged"),
    "Rogue": ("Ranged", "Ranged"),
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

ROLE_MAP = {
    "feral_bear_druid": "Tank", "prot_warrior": "Tank", "prot_paladin": "Tank",
    "holy_priest": "Healer", "resto_druid": "Healer", "resto_shaman": "Healer", "holy_paladin": "Healer",
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


def load_gem_data():
    """Load gem profiles."""
    if os.path.exists(GEMS_PATH):
        with open(GEMS_PATH) as f:
            return json.load(f)
    return {}


def compute_gem_ep(sockets, socket_bonus, weights, gem_profile):
    """Compute EP value of gems + socket bonus + meta bonus for an item's sockets."""
    if not sockets or not gem_profile:
        return 0

    gem_ep = 0
    for color in sockets:
        gem = gem_profile.get(color)
        if gem:
            if "stats" in gem:
                gem_ep += sum(gem["stats"].get(k, 0) * weights.get(k, 0) for k in gem["stats"])
            # Add flat bonusEP for effects that can't be modeled as stats (meta gem procs, etc.)
            gem_ep += gem.get("bonusEP", 0)

    # Add socket bonus EP if all sockets are filled (assume color matching)
    if socket_bonus:
        gem_ep += sum(socket_bonus.get(k, 0) * weights.get(k, 0) for k in socket_bonus)

    return gem_ep


CACHE_TTL_HOURS = 4  # Serve cached gear data for this many hours


def load_gear_cache():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as f:
            return json.load(f)
    return {}


def get_cached_gear(name, server):
    """Return cached WCL data if fresh, else None."""
    cache = load_gear_cache()
    key = f"{name.lower()}@{server.lower()}"
    entry = cache.get(key)
    if not entry:
        return None

    cached_time = entry.get("cached_at", 0)
    age_hours = (datetime.now(timezone.utc).timestamp() - cached_time) / 3600
    if age_hours > CACHE_TTL_HOURS:
        return None

    return entry


def save_gear_cache(name, server, event, report_code, report_time, class_name, actor_id):
    """Cache the WCL gear data locally."""
    cache = load_gear_cache()
    key = f"{name.lower()}@{server.lower()}"
    cache[key] = {
        "cached_at": datetime.now(timezone.utc).timestamp(),
        "event": event,
        "report_code": report_code,
        "report_time": report_time,
        "class_name": class_name,
        "name": name,
    }
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f)


def load_tank_thresholds():
    if os.path.exists(TANK_THRESHOLDS_PATH):
        with open(TANK_THRESHOLDS_PATH) as f:
            return json.load(f)
    return {}


def analyze_tank(spec, event, lines, db, equipped_item_ids):
    """Run tank survival analysis: crit immunity, crush immunity, HP, armor."""
    thresholds = load_tank_thresholds()
    tank_data = thresholds.get(spec)
    if not tank_data:
        return

    lines.append("")
    lines.append(f"**🛡️ Tank Survival Analysis**")

    stamina = event.get("stamina", 0)
    armor = event.get("armor", 0)
    dodge_rating = event.get("dodge", 0)
    parry_rating = event.get("parry", 0)
    block_rating = event.get("block", 0)
    resilience = event.get("resilienceCritTaken", 0)
    agility = event.get("agility", 0)

    conv = tank_data.get("conversions", {})

    # --- Crit Immunity Check ---
    # Sum defense rating from equipped gear, enchants, and gems
    total_defense_rating = 0
    c = db.cursor()

    # Defense from base item stats
    for item_id in equipped_item_ids:
        c.execute("SELECT stats FROM items WHERE item_id = ?", (item_id,))
        row = c.fetchone()
        if row:
            stats = json.loads(row[0])
            total_defense_rating += stats.get("Defense", 0)

    # Defense from gems and enchants (read from WCL gear data)
    # Common TBC defense gems: Thick Dawnstone (+8), Enduring Talasite (+4 def +6 sta)
    # Common defense enchants: +12 defense to gloves, +15 defense to cloak, etc.
    DEFENSE_GEMS = {
        24033: 8,   # Thick Dawnstone (+8 defense)
        24061: 4,   # Enduring Talasite (+4 defense, +6 stamina)
        24054: 4,   # Enduring Talasite
        31101: 5,   # Thick Lionseye (+5 defense)
        35707: 5,   # Thick Lionseye
        32200: 10,  # Thick Shadowsong Amethyst (+10 defense)
        32210: 5,   # Enduring Seaspray Emerald (+5 def +7 sta)
    }
    DEFENSE_ENCHANTS = {
        2933: 15,  # Enchant Cloak - Greater Defense (+15 defense)
        2614: 12,  # Enchant Gloves - Superior Agility... wait this is agi not def
        2648: 7,   # Enchant Boots - Fortitude (+7 stamina... not defense)
        2931: 15,  # Steelweave (+15 defense to cloak)
        2934: 12,  # Enchant Cloak - Dodge (+12 dodge not def)
        1893: 15,  # Enchant Cloak - Greater Defense
        2659: 10,  # Enchant Bracer - Stats
        2999: 15,  # Greater Inscription of Warding (+15 def to shoulder)
        2997: 10,  # Inscription of Warding (+10 def to shoulder)
        3002: 15,  # Greater Inscription of the Knight (+15 defense to shoulder)
        2998: 10,  # Inscription of the Knight (+10 defense to shoulder)
        2841: 16,  # Glyph of the Defender (head, +16 defense)
        3004: 17,  # Glowing Nethergarde Gem (head, +17 defense)
        2991: 16,  # Glyph of the Defender (+16 defense to head from Keepers of Time)
    }

    for gear_item in event.get("gear", []):
        # Sum gem defense — check known gems first, then DB
        for gem in gear_item.get("gems", []):
            gem_id = gem.get("id", 0)
            if gem_id in DEFENSE_GEMS:
                total_defense_rating += DEFENSE_GEMS[gem_id]
            elif gem_id > 0:
                # Try to look up gem in the item DB (gems are items)
                c.execute("SELECT stats FROM items WHERE item_id = ?", (gem_id,))
                gem_row = c.fetchone()
                if gem_row:
                    gem_stats = json.loads(gem_row[0])
                    total_defense_rating += gem_stats.get("Defense", 0)

        # Sum enchant defense from known list
        enchant_id = gear_item.get("permanentEnchant", 0)
        total_defense_rating += DEFENSE_ENCHANTS.get(enchant_id, 0)

    # Convert defense rating to defense skill: 2.37 rating = 1 skill at level 70
    defense_skill_from_gear = total_defense_rating / 2.37
    total_defense = 350 + defense_skill_from_gear
    # Each defense skill above 350 gives 0.04% crit reduction
    defense_crit_pct = defense_skill_from_gear * 0.04

    crit_info = tank_data["crit_immune"]
    talent_crit_reduction = crit_info.get("from_talents", 0)
    resilience_crit_pct = resilience * conv.get("resilience_crit_per_rating", 0.0254)
    total_crit_reduction = defense_crit_pct + resilience_crit_pct + talent_crit_reduction
    crit_needed_pct = 5.6  # base crit chance of boss vs level 70

    if total_crit_reduction >= crit_needed_pct:
        lines.append(f"✅ **Crit Immune:** {total_crit_reduction:.1f}% crit reduction (need {crit_needed_pct:.1f}%)")
    else:
        gap = crit_needed_pct - total_crit_reduction
        lines.append(f"❌ **NOT Crit Immune:** {total_crit_reduction:.1f}% / {crit_needed_pct:.1f}% ({gap:.1f}% short)")

    # Breakdown
    breakdown = f"  Defense: {total_defense:.0f} skill ({total_defense_rating:.0f} rating = {defense_crit_pct:.1f}%)"
    if resilience > 0:
        breakdown += f" + Resilience: {resilience} rating = {resilience_crit_pct:.1f}%"
    if talent_crit_reduction > 0:
        breakdown += f" + {crit_info.get('talent_name', 'Talent')}: {talent_crit_reduction:.1f}%"
    lines.append(breakdown)

    # --- Crush Immunity Check (Warriors/Paladins only) ---
    crush_info = tank_data.get("crush_immune", {})
    avoidance_needed = crush_info.get("total_avoidance_needed", 0)

    if avoidance_needed > 0:
        # Calculate avoidance from ratings
        base_miss = 5.0  # base miss chance vs boss
        dodge_pct = dodge_rating * conv.get("dodge_per_rating", 0.0529) + agility * conv.get("dodge_per_agility", 0.03)
        parry_pct = parry_rating * conv.get("parry_per_rating", 0.0423)
        block_pct = block_rating * conv.get("block_per_rating", 0.0645)
        holy_shield = crush_info.get("holy_shield_block", 0)

        total_avoidance = base_miss + dodge_pct + parry_pct + block_pct + holy_shield
        gap = avoidance_needed - total_avoidance

        method = crush_info.get("method", "")

        if gap <= 0:
            lines.append(f"✅ **Crush Immune:** {total_avoidance:.1f}% total avoidance (need {avoidance_needed}%)")
        else:
            lines.append(f"❌ **NOT Crush Immune:** {total_avoidance:.1f}% / {avoidance_needed}% ({gap:.1f}% short)")

        lines.append(f"  Miss {base_miss:.0f}% + Dodge {dodge_pct:.1f}% + Parry {parry_pct:.1f}% + Block {block_pct:.1f}%{f' + Holy Shield {holy_shield:.0f}%' if holy_shield else ''}")
        if method:
            lines.append(f"  *{method}*")
    else:
        if "method" in crush_info:
            lines.append(f"✅ **Crush Immune:** {crush_info['method']}")

    # --- HP Check ---
    hp_info = tank_data.get("health_baseline", {})
    # Estimate HP: stamina * 10 + base HP (~3000 for most classes)
    estimated_hp = stamina * 10 + 3000
    if spec == "feral_bear_druid":
        # Bear form HP multiplier is applied by the game; WCL stamina is base.
        # Dire Bear form: stamina * 1.25 (Heart of the Wild) then * 10 + base, then * 1.2 (bear form)
        estimated_hp = int((stamina * 1.25 * 10 + 3000) * 1.2)

    minimum = hp_info.get("minimum_hp", 0)
    comfortable = hp_info.get("comfortable_hp", 0)
    well_geared = hp_info.get("well_geared_hp", 0)

    if estimated_hp >= well_geared:
        hp_emoji = "✅"
        hp_tier = "well-geared"
    elif estimated_hp >= comfortable:
        hp_emoji = "✅"
        hp_tier = "comfortable"
    elif estimated_hp >= minimum:
        hp_emoji = "⚠️"
        hp_tier = "minimum"
    else:
        hp_emoji = "❌"
        hp_tier = "below minimum"

    lines.append(f"{hp_emoji} **HP:** ~{estimated_hp:,} unbuffed ({hp_tier})")
    if hp_info.get("notes"):
        lines.append(f"  *{hp_info['notes']}*")

    # --- Armor Check ---
    armor_info = tank_data.get("armor_baseline", {})
    a_min = armor_info.get("minimum", 0)
    a_comf = armor_info.get("comfortable", 0)
    a_well = armor_info.get("well_geared", 0)

    if spec == "feral_bear_druid":
        # Dire Bear multiplier: armor * 4.7 (approx with talents)
        display_armor = int(armor * 4.7)
        armor_note = f" (bear form: {armor} base × 4.7)"
    else:
        display_armor = armor
        armor_note = ""

    if display_armor >= a_well:
        ar_emoji = "✅"
        ar_tier = "well-geared"
    elif display_armor >= a_comf:
        ar_emoji = "✅"
        ar_tier = "comfortable"
    elif display_armor >= a_min:
        ar_emoji = "⚠️"
        ar_tier = "minimum"
    else:
        ar_emoji = "❌"
        ar_tier = "below minimum"

    # Physical damage reduction from armor vs level 73
    dr = display_armor / (display_armor + 11960) * 100
    lines.append(f"{ar_emoji} **Armor:** {display_armor:,}{armor_note} — {dr:.1f}% physical DR ({ar_tier})")


def load_bis_exclusions():
    if os.path.exists(BIS_EXCLUSIONS_PATH):
        with open(BIS_EXCLUSIONS_PATH) as f:
            return json.load(f)
    return {}


def is_excluded_from_bis(item_name, set_name, source_type, exclusions):
    """Check if an item should be excluded from BiS benchmarking. Returns (excluded, emoji, label) or (False, None, None)."""
    for category_key, category in exclusions.items():
        if category_key.startswith("_"):
            continue
        if not isinstance(category, dict):
            continue

        emoji = category.get("emoji", "🚫")
        label = category.get("label", category_key)

        # Source type match
        if source_type in category.get("source_types", []):
            return True, emoji, label

        # Set name match
        if set_name in category.get("set_names", []):
            return True, emoji, label

        # Item name pattern match
        for pattern in category.get("item_name_patterns", []):
            if pattern.lower() in item_name.lower():
                return True, emoji, label

    return False, None, None


def load_tiers():
    if os.path.exists(TIERS_PATH):
        with open(TIERS_PATH) as f:
            return json.load(f).get("tiers", [])
    # Fallback defaults
    return [
        {"min_pct": 95, "label": "⭐"},
        {"min_pct": 85, "label": "🥇"},
        {"min_pct": 70, "label": "🥈"},
        {"min_pct": 50, "label": "🥉"},
        {"min_pct": 0,  "label": "🔨"},
    ]


def get_tier(pct, tiers):
    """Return the tier label for a given % of BiS."""
    for tier in tiers:
        if pct >= tier["min_pct"]:
            return tier["label"]
    return "🔨"


def load_trinket_ep():
    if os.path.exists(TRINKET_EP_PATH):
        with open(TRINKET_EP_PATH) as f:
            return json.load(f)
    return {}


def get_trinket_override(item_id, spec, trinket_data):
    """Check if a trinket has a sim-derived EP override for this spec."""
    entry = trinket_data.get(str(item_id))
    if entry and spec in entry:
        return entry[spec]
    return None


def load_set_bonuses():
    if os.path.exists(SET_BONUSES_PATH):
        with open(SET_BONUSES_PATH) as f:
            return json.load(f)
    return {}


def compute_active_set_bonuses(equipped_sets, set_bonus_data, spec):
    """
    Given a dict of {set_name: piece_count}, return active bonuses.
    Returns list of (set_name, tier, ep, desc).
    """
    active = []
    for set_name, count in equipped_sets.items():
        bonus_info = set_bonus_data.get(set_name)
        if not bonus_info:
            continue

        # Check spec overrides
        overrides = bonus_info.get("spec_overrides", {}).get(spec, {})

        for tier_str in ["2", "3", "4"]:
            tier = int(tier_str)
            if count >= tier and tier_str in bonus_info:
                base_ep = bonus_info[tier_str].get("ep", 0)
                desc = bonus_info[tier_str].get("desc", "")

                # Apply spec override if exists
                ep = overrides.get(tier_str, base_ep)

                if ep > 0:
                    active.append((set_name, tier, ep, desc))

    return active


def log(lines, msg):
    """Append a status line to output."""
    lines.append(msg)


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


def get_wcl_token(lines):
    client_id = os.environ.get("WCL_CLIENT_ID", "")
    client_secret = os.environ.get("WCL_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        log(lines, "ERROR: WCL_CLIENT_ID or WCL_CLIENT_SECRET not set in environment.")
        return None

    try:
        result = http_post(
            "https://www.warcraftlogs.com/oauth/token",
            data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
        )
        return result["access_token"]
    except (HTTPError, URLError, KeyError) as e:
        log(lines, f"ERROR: WCL auth failed: {e}")
        return None


def wcl_query(token, query, lines, retries=2):
    """Query WCL with retry on 503 (server overload)."""
    import time as _time
    for attempt in range(retries + 1):
        try:
            return http_post(
                "https://classic.warcraftlogs.com/api/v2/client",
                json_data={"query": query},
                headers={"Authorization": f"Bearer {token}"},
            )
        except HTTPError as e:
            if e.code == 503 and attempt < retries:
                wait = 5 * (attempt + 1)
                log(lines, f"⏳ WCL server busy (503), retrying in {wait}s... ({attempt + 1}/{retries})")
                _time.sleep(wait)
                continue
            log(lines, f"ERROR: WCL query failed: {e}")
            return None
        except URLError as e:
            log(lines, f"ERROR: WCL query failed: {e}")
            return None


def fetch_from_wcl(name, server, lines):
    """Fetch character gear from WCL. Returns (event, class_name, report_code, report_time) or (None,...) on failure."""
    token = get_wcl_token(lines)
    if not token:
        return None, None, None, None

    result = wcl_query(token, f'''{{
        characterData {{
            character(name: "{name}", serverSlug: "{server}", serverRegion: "us") {{
                classID
                recentReports(limit: 1) {{
                    data {{ code startTime endTime }}
                }}
            }}
        }}
    }}''', lines)

    if not result:
        return None, None, None, None

    char = result.get("data", {}).get("characterData", {}).get("character")
    if not char:
        log(lines, f"**{name}** not found on WCL for server **{server}** (us).")
        log(lines, "- Character name is case-sensitive")
        log(lines, f"- Try: `!gearcheck {name} servername`")
        return None, None, None, None

    reports = char.get("recentReports", {}).get("data", [])
    if not reports:
        log(lines, f"**{name}** exists on WCL but has **no raid logs**.")
        return None, None, None, None

    code = reports[0]["code"]
    report_time = reports[0]["startTime"]
    log(lines, f"Log: {datetime.fromtimestamp(report_time / 1000, tz=timezone.utc).strftime('%Y-%m-%d')} ({code})")

    result = wcl_query(token, f'''{{
        reportData {{ report(code: "{code}") {{
            masterData {{ actors(type: "Player") {{ id name subType server }} }}
        }} }}
    }}''', lines)

    if not result:
        return None, None, None, None

    actors = result.get("data", {}).get("reportData", {}).get("report", {}).get("masterData", {}).get("actors", [])
    actor_id = None
    class_name = "Unknown"
    for actor in actors:
        if actor["name"].lower() == name.lower():
            actor_id = actor["id"]
            class_name = actor.get("subType", "Unknown")
            name = actor["name"]  # Fix case
            break

    if not actor_id:
        log(lines, f"**{name}** not found in report {code}.")
        return None, None, None, None

    result = wcl_query(token, f'''{{
        reportData {{ report(code: "{code}") {{
            events(sourceID: {actor_id}, dataType: CombatantInfo, startTime: 0, endTime: 999999999999) {{ data }}
        }} }}
    }}''', lines)

    if not result:
        return None, None, None, None

    events = result.get("data", {}).get("reportData", {}).get("report", {}).get("events", {}).get("data", [])
    if not events:
        log(lines, f"No gear data for **{name}** in this report.")
        return None, None, None, None

    return events[-1], class_name, code, report_time


def detect_spec(class_name, talents):
    if not talents or len(talents) < 3:
        return None, "unknown talents"

    points = [t.get("id", 0) for t in talents]
    talent_str = f"{points[0]}/{points[1]}/{points[2]}"
    max_tree = points.index(max(points))

    class_specs = SPEC_MAP.get(class_name, {})
    spec = class_specs.get(max_tree)

    if not spec:
        return None, talent_str

    # Warlock refinement: DS/Ruin (21+ demo) vs fire destro
    if class_name == "Warlock" and max_tree == 2:
        spec = "destro_warlock" if points[1] >= 21 else "fire_destro_warlock"

    return spec, talent_str


def main():
    lines = []
    args = sys.argv[1:]

    if not args:
        print("**!gearcheck** — Usage: `!gearcheck <character> [server]`\nDefaults to Dreamscythe US.\nExample: `!gearcheck Brnz`")
        return

    name = args[0]
    server = args[1] if len(args) > 1 else DEFAULT_SERVER

    log(lines, f"Looking up **{name}** on **{server}**...")

    # Check local cache first
    cached = get_cached_gear(name, server)
    if cached:
        age_min = (datetime.now(timezone.utc).timestamp() - cached["cached_at"]) / 60
        log(lines, f"📦 Cached ({age_min:.0f}m ago)")
        event = cached["event"]
        class_name = cached["class_name"]
        name = cached["name"]
        report_code = cached["report_code"]
        report_time = cached["report_time"]
    else:
        # Fetch fresh from WCL
        event, class_name, report_code, report_time = fetch_from_wcl(name, server, lines)
        if not event:
            print("\n".join(lines))
            return
        # Cache for next time
        save_gear_cache(name, server, event, report_code, report_time, class_name, None)

    report_date = datetime.fromtimestamp(report_time / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    talents = event.get("talents", [])
    faction = event.get("faction", -1)  # 1 = Alliance, 0 = Horde
    is_alliance = faction == 1

    # Check for Draenei Heroic Presence in auras (1% hit to party)
    has_heroic_presence = False
    for aura in event.get("auras", []):
        if aura.get("ability") == 6562 or "heroic presence" in aura.get("name", "").lower():
            has_heroic_presence = True
            break

    # Detect spec
    spec, talent_str = detect_spec(class_name, talents)

    if not spec:
        log(lines, f"**{name}** — {class_name} ({talent_str})")
        log(lines, f"Could not map this talent build to a known spec.")
        log(lines, f"Available specs: {', '.join(sorted(f.replace('.json','') for f in os.listdir(WEIGHTS_DIR)))}")
        print("\n".join(lines))
        return

    role = ROLE_MAP.get(spec, "DPS")

    # Step 6: Load weights
    weight_file = os.path.join(WEIGHTS_DIR, f"{spec}.json")
    if not os.path.exists(weight_file):
        log(lines, f"Detected spec **{spec}** but weight file is missing.")
        print("\n".join(lines))
        return

    with open(weight_file) as f:
        spec_data = json.load(f)
    weights = spec_data["weights"]

    # Step 7: Check database
    if not os.path.exists(DB_PATH):
        log(lines, f"Item database not found at {DB_PATH}. Run setup.sh first.")
        print("\n".join(lines))
        return

    db = sqlite3.connect(DB_PATH)

    # Read current phase
    phase = 1
    phase_file = os.path.expanduser("~/.openclaw/workspace/PHASE.md")
    if os.path.exists(phase_file):
        with open(phase_file) as f:
            import re as _re
            m = _re.search(r"Phase (\d+)", f.read())
            if m:
                phase = int(m.group(1))

    # Load all data files
    bis_exclusions = load_bis_exclusions()
    tiers = load_tiers()
    gem_data = load_gem_data()
    gem_profile_name = GEM_PROFILE_MAP.get(spec, "caster")
    gem_profile = gem_data.get(gem_profile_name, {})
    trinket_data = load_trinket_ep()
    set_bonus_data = load_set_bonuses()

    # Pre-compute BiS EP for each slot in current phase (including gems)
    armor_types = spec_data.get("armor_types", [])
    bis_cache = {}  # slot → (best_ep, best_name)
    bis_claimed_items = set()  # Track unique-equipped items already claimed as BiS

    def get_bis(slot, exclude_item_ids=None):
        """Get BiS for a slot. exclude_item_ids prevents double-counting unique items across duplicate slots (Trinket, Ring)."""
        cache_key = f"{slot}:{','.join(str(i) for i in sorted(exclude_item_ids or []))}"
        if cache_key in bis_cache:
            return bis_cache[cache_key]

        # Map display slot back to DB slot for ranged items
        db_slot = slot
        name_filter = None
        if slot in ("Totem", "Idol", "Libram"):
            db_slot = ranged_db_slot
            name_filter = slot  # Filter by item name containing "Totem"/"Idol"/"Libram"

        c = db.cursor()
        query = "SELECT item_id, name, stats, class_restriction, sockets, socket_bonus, source_type, set_name FROM items WHERE slot = ? AND phase <= ? AND quality IN ('Epic', 'Rare')"
        params = [db_slot, phase]

        # Armor type filter for armor slots
        if armor_types and slot not in ("Neck", "Back", "Ring", "Trinket", "Main Hand", "Off Hand", "One Hand", "Two-Hand", "Wand", "Ranged", "Relic"):
            placeholders = ",".join("?" * len(armor_types))
            query += f" AND (armor_type IN ({placeholders}) OR armor_type = '')"
            params.extend(armor_types)

        c.execute(query, params)

        best_ep = 0
        best_name = ""
        best_id = 0
        for row in c.fetchall():
            row_id, row_name = row[0], row[1]

            # Skip items already claimed as BiS in another slot (unique-equipped)
            if exclude_item_ids and row_id in exclude_item_ids:
                continue

            # For relic slots, filter by item name (Totem/Idol/Libram)
            if name_filter and name_filter.lower() not in row_name.lower():
                continue

            cr = json.loads(row[3]) if row[3] else []
            if cr and class_name not in cr:
                continue

            # Skip world boss and crafted BoP items from BiS benchmark
            row_source = row[6] or ""
            row_set = row[7] or ""
            excluded, _, _ = is_excluded_from_bis(row_name, row_set, row_source, bis_exclusions)
            if excluded:
                continue
            item_stats = json.loads(row[2])
            ep = sum(item_stats.get(k, 0) * v for k, v in weights.items())

            sockets = json.loads(row[4]) if row[4] else []
            socket_bonus = json.loads(row[5]) if row[5] else {}
            ep += compute_gem_ep(sockets, socket_bonus, weights, gem_profile)

            # Trinket override
            trinket_override = get_trinket_override(row_id, spec, trinket_data)
            if trinket_override is not None:
                ep = trinket_override

            if ep > best_ep:
                best_ep = ep
                best_name = row_name
                best_id = row_id

        bis_cache[cache_key] = (best_ep, best_name, best_id)
        return best_ep, best_name, best_id

    # Clear status lines, replace with clean output header
    lines.clear()
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")

    lines.append(f"**{name}** — {class_name} {role} ({talent_str})")
    lines.append(f"{spec_data['spec']} | Phase {phase}")
    lines.append(f"Log: {report_date} | Checked: {now}")

    # Stats
    if spec in MELEE_SPECS:
        stat_fields = [("hitMelee", "hit"), ("critMelee", "crit"), ("hasteMelee", "haste"), ("expertise", "expertise")]
    else:
        stat_fields = [("hitSpell", "hit"), ("critSpell", "crit"), ("hasteSpell", "haste")]

    stat_parts = [f"{event.get(k, 0)} {label}" for k, label in stat_fields if event.get(k, 0)]
    if stat_parts:
        lines.append(f"Stats: {', '.join(stat_parts)}")
    lines.append("")

    # Resolve class-specific ranged slot
    ranged_display, ranged_db_slot = CLASS_RANGED_SLOT.get(class_name, ("Ranged", "Ranged"))

    # First pass: count set pieces and collect item IDs for tank analysis
    equipped_sets = {}  # set_name → count
    equipped_items = []  # (slot, item_id, item_name, set_name, ep, source)
    equipped_item_ids = []  # all item IDs for tank defense calculation

    for i, gear_item in enumerate(event.get("gear", [])):
        item_id = gear_item.get("id", 0)
        slot = WCL_SLOT_MAP.get(i)
        if not slot or item_id == 0 or slot == "Shirt":
            continue

        # Resolve ranged slot to class-specific display name
        if slot == "Ranged":
            slot = ranged_display

        c = db.cursor()
        c.execute("SELECT name, stats, sockets, socket_bonus, set_name FROM items WHERE item_id = ?", (item_id,))
        row = c.fetchone()

        if row:
            item_name = row[0]
            item_stats = json.loads(row[1])
            item_sockets = json.loads(row[2]) if row[2] else []
            item_socket_bonus = json.loads(row[3]) if row[3] else {}
            set_name = row[4] or ""

            ep = sum(item_stats.get(k, 0) * v for k, v in weights.items())
            ep += compute_gem_ep(item_sockets, item_socket_bonus, weights, gem_profile)

            # Check for trinket EP override (proc/on-use trinkets)
            trinket_override = get_trinket_override(item_id, spec, trinket_data)
            if trinket_override is not None:
                ep = trinket_override

            # Check source for display tagging
            c2 = db.cursor()
            c2.execute("SELECT source_type FROM items WHERE item_id = ?", (item_id,))
            src_row = c2.fetchone()
            item_source = src_row[0] if src_row else ""

            if set_name:
                equipped_sets[set_name] = equipped_sets.get(set_name, 0) + 1

            equipped_item_ids.append(item_id)
            equipped_items.append((slot, item_id, item_name, set_name, ep, item_source))
        else:
            # Queue unknown item
            try:
                c.execute(
                    "INSERT OR IGNORE INTO items (item_id, name, slot, stats, quality, source_type) VALUES (?, ?, ?, '{}', 'Unknown', 'pending')",
                    (item_id, f"Unknown #{item_id}", slot),
                )
                db.commit()
            except Exception:
                pass
            equipped_items.append((slot, item_id, f"item #{item_id}", "", 0, ""))

    # Compute active set bonuses
    active_bonuses = compute_active_set_bonuses(equipped_sets, set_bonus_data, spec)
    total_set_bonus_ep = sum(b[2] for b in active_bonuses)

    # Second pass: display gear with tier ratings
    total_ep = 0
    total_bis = 0
    tier_counts = {}  # label → count

    # Collect equipped item IDs per slot for unique-equipped dedup
    equipped_ids_by_slot = {}
    for slot, item_id, item_name, set_name, ep, item_source in equipped_items:
        equipped_ids_by_slot.setdefault(slot, []).append(item_id)

    for slot, item_id, item_name, set_name, ep, item_source in equipped_items:
        total_ep += ep

        # For duplicate slots (Trinket, Ring), exclude:
        # 1. Items already claimed as BiS by a prior slot
        # 2. Items already equipped in the other matching slot
        exclude = set(bis_claimed_items)
        if slot in ("Trinket", "Ring"):
            for eid in equipped_ids_by_slot.get(slot, []):
                if eid != item_id:
                    exclude.add(eid)  # Don't benchmark against something you already have in the other slot

        bis_ep, bis_name, bis_id = get_bis(slot, exclude_item_ids=exclude if exclude else None)
        total_bis += bis_ep

        # Track claimed BiS items for unique-equipped dedup
        if bis_id and slot in ("Trinket", "Ring"):
            bis_claimed_items.add(bis_id)

        set_tag = f" [{set_name}]" if set_name else ""

        # Check if this equipped item is a special source
        excluded, excl_emoji, excl_label = is_excluded_from_bis(item_name, set_name, item_source, bis_exclusions)
        if excluded:
            set_tag = f" {excl_emoji} {excl_label}"

        if ep == 0 and "item #" in item_name:
            tier_label = "🔨"
            lines.append(f"{tier_label} **{slot}:** {item_name} (queued) — BiS: {bis_name}")
        elif ep == 0 and slot in ("Totem", "Idol", "Libram"):
            tier_label = "—"
            lines.append(f"{tier_label} **{slot}:** {item_name} (proc-based, not EP-rated)")
            tier_counts[tier_label] = tier_counts.get(tier_label, 0) + 1
            continue
        elif bis_ep > 0:
            pct = (ep / bis_ep) * 100
            delta = bis_ep - ep
            tier_label = get_tier(pct, tiers)

            if delta < 1:
                lines.append(f"{tier_label} **{slot}:** {item_name} ({ep:.0f} EP){set_tag}")
            else:
                lines.append(f"{tier_label} **{slot}:** {item_name} ({ep:.0f} EP) — {delta:+.0f} to {bis_name}{set_tag}")
        else:
            tier_label = "🔨"
            lines.append(f"{tier_label} **{slot}:** {item_name} ({ep:.0f} EP){set_tag}")

        tier_counts[tier_label] = tier_counts.get(tier_label, 0) + 1

    # Tank survival analysis
    if spec in TANK_SPECS:
        analyze_tank(spec, event, lines, db, equipped_item_ids)

    # Active set bonuses
    if active_bonuses:
        lines.append("")
        lines.append("**Active Set Bonuses:**")
        for sname, tier, ep, desc in active_bonuses:
            pieces = equipped_sets[sname]
            lines.append(f"- **{sname}** ({pieces}pc) — {tier}pc: {desc} (+{ep:.0f} EP)")

    # Summary with tier breakdown
    lines.append("")
    grand_total = total_ep + total_set_bonus_ep
    if total_bis > 0:
        overall_pct = (grand_total / total_bis) * 100
        overall_tier = get_tier(overall_pct, tiers)
        set_note = f" (incl. +{total_set_bonus_ep:.0f} set bonus)" if total_set_bonus_ep > 0 else ""
        lines.append(f"{overall_tier} **Total: {grand_total:.0f} / {total_bis:.0f} EP ({overall_pct:.0f}% Phase {phase} BiS)**{set_note}")

        # Tier breakdown
        tier_summary = " ".join(f"{label}×{count}" for label, count in sorted(tier_counts.items(), key=lambda x: -sum(t["min_pct"] for t in tiers if t["label"] == x[0])))
        lines.append(f"Slots: {tier_summary}")
    else:
        lines.append(f"**Total EP: {grand_total:.0f}**")

    hit_cap = spec_data.get("hit_cap", {})
    if hit_cap.get("notes"):
        hit_note = hit_cap["notes"]
        if is_alliance:
            hit_note += " Alliance: Draenei Heroic Presence gives 1% hit to party (12.6 rating free)."
        lines.append(f"*{hit_note}*")

    db.close()
    lines.append(FOOTER)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
