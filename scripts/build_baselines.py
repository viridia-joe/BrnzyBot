"""
scripts/build_baselines.py — build per-boss rotation baselines from WCL top parses.

For each (spec, encounter) pair, fetches the top N parses from WCL global rankings,
pulls each player's cast data, computes cast-per-minute statistics across the sample,
and writes data/baselines/<spec>/<encounter_slug>.json.

Usage:
    # Discover zone encounter IDs (needs WCL creds):
    python3 -m scripts.build_baselines --discover

    # Build baselines for all configured specs + bosses:
    python3 -m scripts.build_baselines

    # Specific spec or encounter only:
    python3 -m scripts.build_baselines --spec ele_shaman
    python3 -m scripts.build_baselines --encounter lady_vashj

    # Limit sample size (default 50, max ~100 per page):
    python3 -m scripts.build_baselines --top 30

Run this once per phase after new content releases. Output files are committed to
the repo; the bot reads them at runtime without any API calls.

Requirements: WCL_CLIENT_ID and WCL_CLIENT_SECRET must be set (same as the bot).
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

# Allow running as a module from repo root.
sys.path.insert(0, str(Path(__file__).parent.parent))

import config  # noqa: E402 — needs sys.path fix above
from core import wcl_client as wcl  # noqa: E402

log = logging.getLogger("build_baselines")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# ---------------------------------------------------------------------------
# Configuration — zones and specs to build baselines for
# ---------------------------------------------------------------------------

# WCL TBC Anniversary zone ID. Zone 1056 = TBC Anniversary SSC+TK (latest parses 2025-2026).
# Zone 1010 = original TBC Classic (2021-22, archived). Zone 1052 = TBC Classic S2 (2022).
TBC_ZONES = {
    "SSC+TK (Anniversary)": 1056,
}

# Encounters to build baselines for: {slug: (encounter_id, display_name)}
# IDs confirmed via --discover against zone 1056 (TBC Anniversary, latest parses June 2026).
ENCOUNTERS: dict[str, tuple[int, str]] = {
    # SSC (Anniversary encounter IDs 100623-100628)
    "hydross_the_unstable":       (100623, "Hydross the Unstable"),
    "the_lurker_below":           (100624, "The Lurker Below"),
    "leotheras_the_blind":        (100625, "Leotheras the Blind"),
    "fathom_lord_karathress":     (100626, "Fathom-Lord Karathress"),
    "morogrim_tidewalker":        (100627, "Morogrim Tidewalker"),
    "lady_vashj":                 (100628, "Lady Vashj"),
    # TK (Anniversary encounter IDs 100730-100733)
    "alar":                       (100730, "Al'ar"),
    "void_reaver":                (100731, "Void Reaver"),
    "high_astromancer_solarian":  (100732, "High Astromancer Solarian"),
    "kaelthas_sunstrider":        (100733, "Kael'thas Sunstrider"),
}

# Specs to build baselines for: {spec_key: (class_id, spec_id)}
# spec_id matches WCL's WCL_SPEC_MAP values in core/gear_cache.py.
# Specs: {spec_key: (className, specName)} — strings as WCL characterRankings expects.
SPECS: dict[str, tuple[str, str]] = {
    "ele_shaman":          ("Shaman",   "Elemental"),
    "enh_shaman":          ("Shaman",   "Enhancement"),
    "bm_hunter":           ("Hunter",   "Beast Mastery"),
    "mm_hunter":           ("Hunter",   "Marksmanship"),
    "survival_hunter":     ("Hunter",   "Survival"),
    "combat_rogue":        ("Rogue",    "Combat"),
    "assassination_rogue": ("Rogue",    "Assassination"),
    "fury_warrior":        ("Warrior",  "Fury"),
    "arms_warrior":        ("Warrior",  "Arms"),
    "ret_paladin":         ("Paladin",  "Retribution"),
    "feral_cat_druid":     ("Druid",    "Feral"),
    "balance_druid":       ("Druid",    "Balance"),
    "fire_mage":           ("Mage",     "Fire"),
    "arcane_mage":         ("Mage",     "Arcane"),
    "frost_mage":          ("Mage",     "Frost"),
    "shadow_priest":       ("Priest",   "Shadow"),
    "affliction_warlock":  ("Warlock",  "Affliction"),
    "destro_warlock":      ("Warlock",  "Destruction"),
}

BASELINE_DIR = Path(__file__).parent.parent / "data" / "baselines"
TOP_N = 50          # parses to fetch per spec per boss
MIN_SAMPLE = 10     # skip writing if we got fewer than this
# Spells that appear in fewer than this fraction of parses are excluded from baseline.
MIN_PRESENCE = 0.20


# ---------------------------------------------------------------------------
# Encounter ID discovery
# ---------------------------------------------------------------------------

def discover_encounters() -> None:
    """Print all encounter IDs for configured zones. Use output to fill ENCOUNTERS."""
    for zone_name, zone_id in TBC_ZONES.items():
        print(f"\n=== {zone_name} (zone {zone_id}) ===")
        encounters = wcl.get_zone_encounters(zone_id)
        if not encounters:
            print("  (no data — check credentials or zone ID)")
            continue
        for enc in encounters:
            slug = _slugify(enc["name"])
            print(f'    "{slug}": ({enc["id"]}, "{enc["name"]}"),')


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def fetch_top_parses(
    encounter_id: int, class_name: str, spec_name: str, top_n: int
) -> list[dict]:
    """Fetch up to top_n ranking entries for this encounter+spec."""
    results = []
    page = 1
    while len(results) < top_n:
        log.debug("  rankings page %d …", page)
        data = wcl.get_encounter_rankings(encounter_id, class_name, spec_name, page)
        entries = data.get("rankings") or []
        if not entries:
            break
        results.extend(entries)
        if not data.get("hasMorePages") or len(results) >= top_n:
            break
        page += 1
    return results[:top_n]


def fetch_cast_cpm(
    report_code: str, fight_id: int, duration_ms: int
) -> dict[str, float] | None:
    """
    Fetch a player's casts for one fight and return {spell_name: casts_per_minute}.
    Returns None on fetch failure.
    """
    if duration_ms <= 0:
        return None
    duration_min = duration_ms / 60_000.0

    try:
        abilities = wcl.get_abilities(report_code)
        name_by_id = {a.get("gameID"): a.get("name") for a in abilities}

        # Find the actor ID for this fight. We need master actors for the report.
        actors = wcl.get_master_actors(report_code)
        # We don't know the player name directly from the ranking entry's report field,
        # but we can get all casts for the fight and aggregate across all sources —
        # then we'll take the player with the most casts of core spells.
        # Better: fetch casts without sourceID filter and pick the top caster.
        all_casts = wcl.get_casts(report_code, fight_id, source_id=None)
    except Exception as e:
        log.warning("    cast fetch failed for %s fight %d: %s", report_code, fight_id, e)
        return None

    if not all_casts:
        return None

    # Aggregate by source → spell → count
    by_source: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for ev in all_casts:
        if ev.get("type") != "cast":
            continue
        src = ev.get("sourceID", -1)
        gid = ev.get("abilityGameID")
        nm = name_by_id.get(gid, f"Spell#{gid}")
        by_source[src][nm] += 1

    if not by_source:
        return None

    # Pick the source with the most total casts (the DPS player for this parse).
    top_src = max(by_source, key=lambda s: sum(by_source[s].values()))
    counts = by_source[top_src]
    return {nm: cnt / duration_min for nm, cnt in counts.items()}


def compute_percentiles(values: list[float]) -> dict[str, float]:
    """Compute p25/p50/p75/p95 from a list of floats."""
    if not values:
        return {}
    s = sorted(values)
    n = len(s)

    def pct(p: float) -> float:
        idx = (p / 100) * (n - 1)
        lo, hi = int(idx), min(int(idx) + 1, n - 1)
        return round(s[lo] + (idx - lo) * (s[hi] - s[lo]), 3)

    return {"p25": pct(25), "p50": pct(50), "p75": pct(75), "p95": pct(95)}


def build_baseline(
    spec_key: str,
    encounter_slug: str,
    encounter_id: int,
    encounter_name: str,
    class_name: str,
    spec_name: str,
    top_n: int,
) -> dict | None:
    """
    Build one baseline dict. Returns None if insufficient data.
    """
    log.info("Building %s / %s …", spec_key, encounter_slug)

    parses = fetch_top_parses(encounter_id, class_name, spec_name, top_n)
    if not parses:
        log.warning("  No parses found — skipping")
        return None

    log.info("  Fetched %d ranking entries, pulling cast data …", len(parses))

    # {spell_name: [cpm_parse1, cpm_parse2, ...]}
    spell_cpms: dict[str, list[float]] = defaultdict(list)
    good = 0
    for i, entry in enumerate(parses):
        report = entry.get("report") or {}
        code = report.get("code")
        fight_id = report.get("fightID")
        duration_ms = int(entry.get("duration") or 0)
        if not code or not fight_id:
            continue

        log.debug("  [%d/%d] %s report %s fight %d (%.1fs)",
                  i + 1, len(parses), entry.get("name", "?"),
                  code, fight_id, duration_ms / 1000)

        cpm = fetch_cast_cpm(code, fight_id, duration_ms)
        if cpm is None:
            continue

        for spell, rate in cpm.items():
            spell_cpms[spell].append(rate)
        good += 1
        time.sleep(0.1)  # extra courtesy gap on top of wcl_client's own limiter

    if good < MIN_SAMPLE:
        log.warning("  Only %d usable parses (need %d) — skipping", good, MIN_SAMPLE)
        return None

    log.info("  %d / %d parses usable", good, len(parses))

    # Filter spells that appear in fewer than MIN_PRESENCE fraction of parses.
    min_count = math.ceil(good * MIN_PRESENCE)
    spells_out = {}
    for spell, cpms in sorted(spell_cpms.items()):
        if len(cpms) < min_count:
            continue
        # Zero-fill missing parses (spell not cast in some pulls).
        full = cpms + [0.0] * (good - len(cpms))
        spells_out[spell] = compute_percentiles(full)

    return {
        "spec": spec_key,
        "encounter": encounter_name,
        "encounter_id": encounter_id,
        "sample_size": good,
        "generated": time.strftime("%Y-%m-%d"),
        "spells": spells_out,
    }


def write_baseline(spec_key: str, encounter_slug: str, data: dict) -> None:
    out_dir = BASELINE_DIR / spec_key
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{encounter_slug}.json"
    # Write to a temp file then atomic-rename so the bot never reads a partial file.
    tmp_path = out_path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, out_path)  # atomic on POSIX and Windows
    log.info("  Written → %s", out_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Build WCL-derived rotation baselines.")
    parser.add_argument("--discover", action="store_true",
                        help="Print encounter IDs for configured zones and exit")
    parser.add_argument("--spec", help="Only build for this spec key (e.g. ele_shaman)")
    parser.add_argument("--encounter", help="Only build for this encounter slug (e.g. lady_vashj)")
    parser.add_argument("--top", type=int, default=TOP_N,
                        help=f"Number of top parses to sample (default {TOP_N})")
    args = parser.parse_args()

    if not os.environ.get("WCL_CLIENT_ID") or not os.environ.get("WCL_CLIENT_SECRET"):
        log.error("WCL_CLIENT_ID and WCL_CLIENT_SECRET must be set.")
        sys.exit(1)

    if args.discover:
        discover_encounters()
        return

    specs = {args.spec: SPECS[args.spec]} if args.spec else SPECS
    encounters = (
        {args.encounter: ENCOUNTERS[args.encounter]} if args.encounter else ENCOUNTERS
    )

    missing_ids = [slug for slug, (eid, _) in encounters.items() if eid == 0]
    if missing_ids:
        log.warning(
            "The following encounters have no ID yet (run --discover first): %s",
            ", ".join(missing_ids),
        )
        encounters = {s: v for s, v in encounters.items() if v[0] != 0}

    if not encounters:
        log.error("No encounters with valid IDs. Run --discover to populate encounter IDs.")
        sys.exit(1)

    total = len(specs) * len(encounters)
    done = 0
    for spec_key, (class_name, spec_name) in specs.items():
        for enc_slug, (enc_id, enc_name) in encounters.items():
            done += 1
            log.info("[%d/%d] %s × %s", done, total, spec_key, enc_slug)
            try:
                result = build_baseline(
                    spec_key, enc_slug, enc_id, enc_name,
                    class_name, spec_name, args.top,
                )
                if result:
                    write_baseline(spec_key, enc_slug, result)
            except KeyboardInterrupt:
                log.info("Interrupted.")
                sys.exit(0)
            except Exception as e:
                log.error("  Failed: %s", e)

    log.info("Done.")


if __name__ == "__main__":
    main()
