#!/usr/bin/env python3
"""
Build or update professions.json from tbc_items.db.

Run on jarvis after the item DB is populated:
    python3 build_professions_db.py

Queries items by name patterns for known BOP crafted gear and writes
~/.openclaw/data/professions.json mapping item_id (str) → profession.

Why name-based matching: item IDs are stable in TBC but the crafted_by or
binding fields are unreliable in third-party DBs. Matching on canonical item
names is more robust than hoping the import preserved the right flags.

Edit KNOWN_CRAFTED below to add new items when a phase drops.
"""

import json
import os
import sqlite3

DB_PATH   = os.path.expanduser("~/.openclaw/data/tbc_items.db")
OUT_PATH  = os.path.expanduser("~/.openclaw/data/professions.json")

# ── Known BOP crafted items: (name_substring, profession) ─────────────────
# name_substring is matched case-insensitively via LIKE '%…%'.
# The first match wins, so more-specific patterns come first.
KNOWN_CRAFTED: list[tuple[str, str]] = [

    # ── Tailoring — Frozen Shadoweave (shadow warlock / shadow priest) ─────
    ("Frozen Shadoweave Robe",        "Tailoring"),
    ("Frozen Shadoweave Shoulders",   "Tailoring"),
    ("Frozen Shadoweave Boots",       "Tailoring"),

    # ── Tailoring — Spellfire (fire mage) ─────────────────────────────────
    ("Spellfire Robe",                "Tailoring"),
    ("Spellfire Gloves",              "Tailoring"),
    ("Spellfire Belt",                "Tailoring"),

    # ── Tailoring — Primal Mooncloth (holy priest / resto druid) ──────────
    ("Primal Mooncloth Robe",         "Tailoring"),
    ("Primal Mooncloth Shoulders",    "Tailoring"),
    ("Primal Mooncloth Belt",         "Tailoring"),

    # ── Tailoring — Spellstrike (arcane / fire mage, T4/T5 era) ───────────
    ("Spellstrike Hood",              "Tailoring"),
    ("Spellstrike Pants",             "Tailoring"),

    # ── Tailoring — Battlecast (destro warlock, T4/T5 era) ────────────────
    ("Battlecast Hood",               "Tailoring"),
    ("Battlecast Pants",              "Tailoring"),

    # ── Tailoring — Whitemend (healer, T5/T6 era) ─────────────────────────
    ("Whitemend Hood",                "Tailoring"),
    ("Whitemend Pants",               "Tailoring"),

    # ── Engineering — Goggles (phase 1 → phase 3) ─────────────────────────
    # These are all head-slot, BOP, require 350/375 Engineering to wear.
    ("Destruction Holo-Gogs",         "Engineering"),
    ("Deathblow X11 Goggles",         "Engineering"),
    ("Tankatronic Goggles",           "Engineering"),
    ("Living Replicator Specs",       "Engineering"),
    ("Cogspinner Goggles",            "Engineering"),
    ("Magnified Moon Specs",          "Engineering"),
    ("Surestrike Goggles v2.0",       "Engineering"),
    ("Hyper-Vision Goggles",          "Engineering"),
    ("Gadgetstorm Goggles",           "Engineering"),
    ("Justicebringer 2000 Specs",     "Engineering"),
    ("Gnomish Power Goggles",         "Engineering"),
    ("Wonderheal XT40 Shades",        "Engineering"),
    ("Primal-Storm Goggles",          "Engineering"),

    # ── Leatherworking — Ebon Netherscale (physical mail/leather melee) ───
    ("Ebon Netherscale Breastplate",  "Leatherworking"),
    ("Ebon Netherscale Bracers",      "Leatherworking"),
    ("Ebon Netherscale Belt",         "Leatherworking"),

    # ── Leatherworking — Windhawk (caster leather: elem shaman / druid) ───
    ("Windhawk Hauberk",              "Leatherworking"),
    ("Windhawk Bracers",              "Leatherworking"),
    ("Windhawk Belt",                 "Leatherworking"),

    # ── Leatherworking — Primalstrike (physical leather/mail) ─────────────
    ("Primalstrike Vest",             "Leatherworking"),
    ("Primalstrike Bracers",          "Leatherworking"),
    ("Primalstrike Belt",             "Leatherworking"),

    # ── Blacksmithing — specialty weapons / armor (BOP on equip in TBC) ──
    # Most TBC BS items are BOE, but some specialization items are BOP at use.
    # Adjust based on what the item DB says once imported.
    ("Stormherald",                   "Blacksmithing"),
    ("The Planar Edge",               "Blacksmithing"),
    ("Wicked Edge of the Planes",     "Blacksmithing"),
    ("Blazeguard",                    "Blacksmithing"),
    ("Blazefury",                     "Blacksmithing"),
    ("Felsteel Longblade",            "Blacksmithing"),
    ("Lionheart Champion",            "Blacksmithing"),
    ("Lionheart Executioner",         "Blacksmithing"),
    ("Shard of Contempt",             "Blacksmithing"),   # trinket, P5
    ("Black Felsteel Bracers",        "Blacksmithing"),
    ("Ragesteel Shoulders",           "Blacksmithing"),
    ("Ragesteel Gloves",              "Blacksmithing"),
    ("Ragesteel Breastplate",         "Blacksmithing"),
    ("Dawnsteel Shoulders",           "Blacksmithing"),
    ("Dawnsteel Bracers",             "Blacksmithing"),

    # ── Alchemy — stones (trinkets) ────────────────────────────────────────
    ("Assassin's Alchemist Stone",    "Alchemy"),
    ("Guardian's Alchemist Stone",    "Alchemy"),
    ("Mercurial Alchemist Stone",     "Alchemy"),
    ("Redeemer's Alchemist Stone",    "Alchemy"),
    ("Sorcerer's Alchemist Stone",    "Alchemy"),
]


def build(db_path: str, out_path: str) -> None:
    if not os.path.exists(db_path):
        print(f"ERROR: DB not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    c    = conn.cursor()

    # Load existing to preserve any hand-edited entries
    existing: dict[str, str] = {}
    if os.path.exists(out_path):
        with open(out_path) as f:
            existing = json.load(f)

    found = dict(existing)
    matched = 0
    not_found: list[str] = []

    for name_pattern, profession in KNOWN_CRAFTED:
        c.execute("SELECT item_id, name FROM items WHERE name LIKE ?",
                  (f"%{name_pattern}%",))
        rows = c.fetchall()
        if not rows:
            not_found.append(name_pattern)
            continue
        for item_id, full_name in rows:
            key = str(item_id)
            if key not in found:
                found[key] = profession
                matched += 1
                print(f"  [{profession}] {item_id} — {full_name}")

    conn.close()

    with open(out_path, "w") as f:
        json.dump(found, f, indent=2, sort_keys=True)

    print(f"\nWrote {len(found)} entries to {out_path}")
    print(f"  New this run: {matched}")
    if not_found:
        print(f"  Not found in DB ({len(not_found)} items):")
        for n in not_found:
            print(f"    - {n}")


if __name__ == "__main__":
    build(DB_PATH, OUT_PATH)
