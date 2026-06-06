"""
scripts/build_baselines.py — build per-boss rotation baselines from WCL top parses.

Fetches top-N TBC Anniversary parses per (spec, encounter), computes cast-per-minute
percentiles (p25/p50/p75/p95), writes data/baselines/<spec>/<encounter_slug>.json.
Bot reads these at runtime (zero API calls). Commit the output after each phase.

Credentials: set WCL_CLIENT_ID and WCL_CLIENT_SECRET in environment or a .env file:
    export $(grep -v '^#' ~/brnzybot.env | xargs)
    python3 -m scripts.build_baselines

Usage:
    --discover          print encounter IDs for configured zones and exit
    --spec ele_shaman   build only this spec
    --encounter alar    build only this encounter
    --top 30            sample size (default 50)
    --force             overwrite existing baseline files (default: skip)
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

sys.path.insert(0, str(Path(__file__).parent.parent))

import config  # noqa: E402
from core import wcl_client as wcl  # noqa: E402

log = logging.getLogger("build_baselines")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# TBC Anniversary: SSC + TK share zone 1056. Original TBC (zone 1010) is archived.
TBC_ZONES = {"SSC+TK (Anniversary)": 1056}

# IDs confirmed via --discover against zone 1056 (parses current as of June 2026).
ENCOUNTERS: dict[str, tuple[int, str]] = {
    "hydross_the_unstable":      (100623, "Hydross the Unstable"),
    "the_lurker_below":          (100624, "The Lurker Below"),
    "leotheras_the_blind":       (100625, "Leotheras the Blind"),
    "fathom_lord_karathress":    (100626, "Fathom-Lord Karathress"),
    "morogrim_tidewalker":       (100627, "Morogrim Tidewalker"),
    "lady_vashj":                (100628, "Lady Vashj"),
    "alar":                      (100730, "Al'ar"),
    "void_reaver":               (100731, "Void Reaver"),
    "high_astromancer_solarian": (100732, "High Astromancer Solarian"),
    "kaelthas_sunstrider":       (100733, "Kael'thas Sunstrider"),
}

# (className, specName) strings as WCL characterRankings expects.
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
TOP_N        = 50    # parses per spec × boss
MIN_SAMPLE   = 10   # skip if fewer usable parses
MIN_PRESENCE = 0.20  # exclude spells seen in <20% of parses


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_encounters() -> None:
    """Print encounter IDs for all configured zones (update ENCOUNTERS after)."""
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
# Pipeline
# ---------------------------------------------------------------------------

def fetch_top_parses(
    encounter_id: int, class_name: str, spec_name: str, top_n: int
) -> list[dict]:
    """Fetch up to top_n ranking entries, paginating as needed."""
    results, page = [], 1
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
    Return {spell_name: casts_per_minute} for the top caster in one fight.
    Returns None on any fetch failure or zero-duration fight.
    """
    if duration_ms <= 0:
        return None
    duration_min = duration_ms / 60_000.0
    try:
        abilities = wcl.get_abilities(report_code)
        name_by_id = {a.get("gameID"): a.get("name") for a in abilities}
        all_casts = wcl.get_casts(report_code, fight_id, source_id=None)
    except Exception as e:
        log.warning("    cast fetch failed for %s fight %d: %s", report_code, fight_id, e)
        return None

    if not all_casts:
        return None

    # Aggregate by source; pick the one with the most casts (the DPS player).
    by_source: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for ev in all_casts:
        if ev.get("type") != "cast":
            continue
        by_source[ev.get("sourceID", -1)][name_by_id.get(ev.get("abilityGameID"), f"Spell#{ev.get('abilityGameID')}")] += 1

    if not by_source:
        return None

    top_src = max(by_source, key=lambda s: sum(by_source[s].values()))
    counts = by_source[top_src]
    return {nm: cnt / duration_min for nm, cnt in counts.items()}


def compute_percentiles(values: list[float]) -> dict[str, float]:
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
    log.info("Building %s / %s …", spec_key, encounter_slug)
    parses = fetch_top_parses(encounter_id, class_name, spec_name, top_n)
    if not parses:
        log.warning("  No parses returned — skipping")
        return None

    log.info("  Fetched %d ranking entries, pulling cast data …", len(parses))
    spell_cpms: dict[str, list[float]] = defaultdict(list)
    good = 0

    for i, entry in enumerate(parses):
        report   = entry.get("report") or {}
        code     = report.get("code")
        fight_id = report.get("fightID")
        duration = int(entry.get("duration") or 0)
        if not code or not fight_id:
            continue

        log.debug("  [%d/%d] %s %s fight %d (%.0fs)",
                  i + 1, len(parses), entry.get("name", "?"), code, fight_id, duration / 1000)

        cpm = fetch_cast_cpm(code, fight_id, duration)
        if cpm is None:
            continue
        for spell, rate in cpm.items():
            spell_cpms[spell].append(rate)
        good += 1
        time.sleep(0.1)  # courtesy gap on top of wcl_client's own rate limiter

    if good < MIN_SAMPLE:
        log.warning("  Only %d usable parses (need %d) — skipping", good, MIN_SAMPLE)
        return None

    log.info("  %d / %d parses usable", good, len(parses))

    # Zero-fill missing parses; filter spells present in <MIN_PRESENCE of pulls.
    min_count = math.ceil(good * MIN_PRESENCE)
    spells_out = {}
    for spell, cpms in sorted(spell_cpms.items()):
        if len(cpms) < min_count:
            continue
        full = cpms + [0.0] * (good - len(cpms))
        spells_out[spell] = compute_percentiles(full)

    return {
        "spec":         spec_key,
        "encounter":    encounter_name,
        "encounter_id": encounter_id,
        "sample_size":  good,
        "generated":    time.strftime("%Y-%m-%d"),
        "spells":       spells_out,
    }


def write_baseline(spec_key: str, encounter_slug: str, data: dict) -> None:
    out_dir  = BASELINE_DIR / spec_key
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{encounter_slug}.json"
    tmp_path = out_path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, out_path)   # atomic — bot never reads a partial file
    log.info("  Written → %s", out_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Build WCL-derived rotation baselines.")
    parser.add_argument("--discover", action="store_true",
                        help="Print encounter IDs for configured zones and exit")
    parser.add_argument("--spec",      help="Only build for this spec key (e.g. ele_shaman)")
    parser.add_argument("--encounter", help="Only build for this encounter slug (e.g. lady_vashj)")
    parser.add_argument("--top",       type=int, default=TOP_N,
                        help=f"Top-parse sample size (default {TOP_N})")
    parser.add_argument("--force",     action="store_true",
                        help="Overwrite existing baseline files (default: skip)")
    args = parser.parse_args()

    if not os.environ.get("WCL_CLIENT_ID") or not os.environ.get("WCL_CLIENT_SECRET"):
        log.error("WCL_CLIENT_ID and WCL_CLIENT_SECRET must be set in environment.")
        log.error("  export \$(grep -v '^#' ~/brnzybot.env | xargs)")
        sys.exit(1)

    if args.discover:
        discover_encounters()
        return

    specs     = {args.spec: SPECS[args.spec]} if args.spec else SPECS
    encounters = (
        {args.encounter: ENCOUNTERS[args.encounter]} if args.encounter else ENCOUNTERS
    )

    # Validate unknown keys immediately.
    for key in list(specs):
        if key not in SPECS:
            log.error("Unknown spec: %s. Valid: %s", key, ", ".join(SPECS))
            sys.exit(1)
    for key in list(encounters):
        if key not in ENCOUNTERS:
            log.error("Unknown encounter: %s. Valid: %s", key, ", ".join(ENCOUNTERS))
            sys.exit(1)

    total, done, skipped, failed = len(specs) * len(encounters), 0, 0, 0

    for spec_key, (class_name, spec_name) in specs.items():
        for enc_slug, (enc_id, enc_name) in encounters.items():
            done += 1
            out_path = BASELINE_DIR / spec_key / f"{enc_slug}.json"

            if out_path.exists() and not args.force:
                log.info("[%d/%d] SKIP %s × %s (already exists; use --force to rebuild)",
                         done, total, spec_key, enc_slug)
                skipped += 1
                continue

            log.info("[%d/%d] %s × %s", done, total, spec_key, enc_slug)
            try:
                result = build_baseline(
                    spec_key, enc_slug, enc_id, enc_name,
                    class_name, spec_name, args.top,
                )
                if result:
                    write_baseline(spec_key, enc_slug, result)
                else:
                    failed += 1
            except KeyboardInterrupt:
                log.info("Interrupted. Progress so far is saved.")
                sys.exit(0)
            except Exception as e:
                log.error("  FAILED: %s", e)
                failed += 1

    log.info("Done. built=%d skipped=%d failed=%d",
             done - skipped - failed, skipped, failed)


if __name__ == "__main__":
    main()
