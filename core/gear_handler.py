#!/usr/bin/env python3
"""
BrnzyBot Gear Handler — entry point wired into the wow-commands hook.

Reads the Discord message from stdin. If triage classifies it as a gear
question, runs the full pipeline and prints the answer to stdout. If not
a gear question, prints nothing — the hook falls through to the Claude agent.

Pipeline:
  triage (8B)  →  gear_cache (WCL/SQLite)  →  gear_context (deterministic)
  →  gear_reasoning (32B generator-critic loop)  →  stdout

The thinking message is posted to Discord as a fire-and-forget subprocess
before the slow LLM calls begin, so the user sees immediate feedback.
"""

import json
import logging
import os
import sqlite3
import subprocess
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [gear_handler] %(message)s",
)
log = logging.getLogger(__name__)

# Load credentials from .env when running outside systemd
_ENV_PATH = os.path.expanduser("~/.openclaw/data/.env")
if os.path.exists(_ENV_PATH):
    with open(_ENV_PATH) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

sys.path.insert(0, os.path.dirname(__file__))

import config
from discord_post import post_to_discord
from triage import triage
from gear_cache import get_gear
from gear_context import build_context
from gear_reasoning import reason
from node_health import check_nodes

CHARACTERS_PATH = os.path.expanduser("~/.openclaw/data/characters.json")
ITEM_DB_PATH    = os.path.expanduser("~/.openclaw/data/tbc_items.db")


# ---------------------------------------------------------------------------
# Character registry
# ---------------------------------------------------------------------------

def load_characters() -> dict:
    """
    Load character → spec/realm mapping.
    Falls back to hardcoded defaults if the file doesn't exist.
    """
    if os.path.exists(CHARACTERS_PATH):
        with open(CHARACTERS_PATH) as f:
            return json.load(f)
    return {
        "brnz":  {"spec": "destro_warlock", "realm": config.SERVER_SLUG, "region": "us"},
        "brnzy": {"spec": "ele_shaman",     "realm": config.SERVER_SLUG, "region": "us"},
    }


def resolve_character(name: str, characters: dict) -> dict | None:
    return characters.get(name.lower())


# ---------------------------------------------------------------------------
# Thinking message — fire-and-forget
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    message = sys.stdin.read().strip()
    if not message:
        sys.exit(0)

    log.info("Received message (%d chars)", len(message))

    # ── Step 1: Triage ──────────────────────────────────────────────────────
    tr = triage(message)
    log.info("Triage: intent=%s character=%r requires_gear=%s",
             tr.intent, tr.character, tr.requires_gear)

    if not tr.requires_gear:
        # Not a gear question — exit silently, Claude handles it
        sys.exit(0)

    characters = load_characters()

    # ── Step 2: Resolve character ───────────────────────────────────────────
    char_name = tr.character or "Brnz"
    char_data = resolve_character(char_name, characters)

    if not char_data:
        log.warning("Unknown character %r — falling through to Claude", char_name)
        sys.exit(0)

    spec   = char_data["spec"]
    realm  = char_data["realm"]
    region = char_data.get("region", "us")

    # ── Step 3: Fetch gear (WCL or SQLite cache) ────────────────────────────
    # (thinking message is posted by handler.ts before spawning this process)
    item_db = None
    if os.path.exists(ITEM_DB_PATH):
        item_db = sqlite3.connect(ITEM_DB_PATH)

    try:
        snapshot = get_gear(char_name, realm, spec, region=region, item_db_conn=item_db)
    finally:
        if item_db:
            item_db.close()

    if snapshot is None:
        post_to_discord(
            f"I can't locate gear data for **{char_name}** right now — "
            "WCL is unreachable and I have no cached snapshot. "
            "Try again in a moment, or run `!gearcheck` to force a refresh."
        )
        return

    # ── Step 5: Build deterministic context ────────────────────────────────
    context = build_context(snapshot, spec)
    log.info("Context built: hit_status=%s set_bonuses=%d",
             context.hit_cap.status, len(context.active_set_bonuses))

    # ── Step 5b: Check which 32B nodes are actually free ───────────────────
    node_status = check_nodes(post_alerts=False)
    log.info("Node status: available=%s busy=%s down=%s",
             list(node_status.available), list(node_status.busy), list(node_status.down))

    # ── Step 6: Generator-critic loop ──────────────────────────────────────
    # Thinking message already posted — pass a no-op post_fn.
    # Answer is posted directly to Discord — not returned via stdout —
    # because this process runs detached (hook already returned).
    answer = reason(context, tr, message, post_fn=lambda _: None,
                    node_status=node_status)
    post_to_discord(answer)


if __name__ == "__main__":
    main()
