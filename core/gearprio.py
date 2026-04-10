#!/usr/bin/env python3
"""
BrnzyBot gear priority optimizer — pure logic entry point.

Called by cogs/gear.py. Returns an OptimalSet (or raises / returns an error
string). Never posts to Discord directly — that's the cog's responsibility.

Modes:
    run(char_name, guild_id, mode="upgrades", max_changes=3) -> OptimalSet | str
        str return = human-readable error message for the user.
"""

import json
import logging
import os
import sqlite3
from typing import Union

log = logging.getLogger(__name__)

import config
from core.gear_cache import get_gear
from core.gear_optimizer import OptimizeParams, OptimalSet, solve_bis, solve_upgrades

ITEM_DB_PATH = os.path.expanduser("~/.openclaw/data/tbc_items.db")

def run(
    char_name: str,
    spec: str,
    realm: str,
    region: str = "us",
    mode: str = "upgrades",
    max_changes: int = 3,
) -> Union[OptimalSet, str]:
    """
    Run the gear optimizer for a character.

    Returns OptimalSet on success, or a human-readable error string on failure.
    Never touches Discord — that's the caller's job.
    """
    if not os.path.exists(ITEM_DB_PATH):
        return (
            "Item database not found at `~/.openclaw/data/tbc_items.db`. "
            "The optimizer requires a populated item DB."
        )

    item_db = sqlite3.connect(ITEM_DB_PATH)
    try:
        snapshot = get_gear(char_name, realm, spec, region=region, item_db_conn=item_db)
        if snapshot is None:
            return (
                f"Can't locate gear data for **{char_name}** — WCL unreachable and "
                "no cached snapshot. Try again in a moment or run `/gearcheck`."
            )

        params = OptimizeParams(
            phase=config.CURRENT_PHASE,
            hit_buff_in_raid=False,
            fight_length_sec=120,
            mode=mode,
            max_changes=max_changes,
            include_pvp=False,
            include_world_boss=False,
        )

        log.info("Running %s for %s (%s), max_changes=%d", mode, char_name, spec, max_changes)

        if mode == "bis":
            result = solve_bis(char_name, spec, item_db, params, snapshot=snapshot)
        else:
            result = solve_upgrades(
                char_name, spec, item_db, params,
                snapshot=snapshot, max_changes=max_changes,
            )

    finally:
        item_db.close()

    if result.solver_status == "error":
        return f"Optimizer failed for **{char_name}**: {'; '.join(result.warnings)}"

    log.info("Solve complete: %s %s", mode, char_name)
    return result
