"""
BrnzyBot configuration.

All runtime config is sourced from environment variables (loaded from
~/.openclaw/data/.env on startup if the file exists).

Per-server config (verbosity, characters, realm) lives in the SQLite DB
managed by db/server_config.py — not here.
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Load .env on import (same pattern as existing gear scripts)
# ---------------------------------------------------------------------------
_ENV_PATH = os.path.expanduser("~/.openclaw/data/.env")
if os.path.exists(_ENV_PATH):
    with open(_ENV_PATH) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------
DISCORD_TOKEN: str = os.environ.get("DISCORD_BOT_TOKEN", "")

# Command prefix for legacy !commands (slash commands are the primary path)
COMMAND_PREFIX: str = os.environ.get("COMMAND_PREFIX", "!")


# ---------------------------------------------------------------------------
# WCL
# ---------------------------------------------------------------------------
WCL_CLIENT_ID:     str = os.environ.get("WCL_CLIENT_ID", "")
WCL_CLIENT_SECRET: str = os.environ.get("WCL_CLIENT_SECRET", "")


# ---------------------------------------------------------------------------
# Paths — shared with gear scripts
# ---------------------------------------------------------------------------
DATA_DIR          = os.path.expanduser("~/.openclaw/data")
ITEM_DB_PATH      = os.path.join(DATA_DIR, "tbc_items.db")
WEIGHTS_DIR       = os.path.join(DATA_DIR, "weights")
BOT_DB_PATH       = os.path.join(DATA_DIR, "brnzybot.db")
STRATEGY_DB_PATH  = os.path.join(DATA_DIR, "tbc_strategy.db")
STRATEGY_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "strategy")


# ---------------------------------------------------------------------------
# LiteLLM / inference
# ---------------------------------------------------------------------------
LITELLM_BASE_URL: str = os.environ.get("LITELLM_BASE_URL", "http://10.0.0.186:4000")
LITELLM_API_KEY:  str = os.environ.get("LITELLM_API_KEY", "sk-1234")

# Model routing tiers (match litellm_config.yaml model names)
MODEL_TRIAGE:     str = os.environ.get("MODEL_TRIAGE",     "ollama/qwen2.5:14b")
MODEL_GEAR_GEN:   str = os.environ.get("MODEL_GEAR_GEN",   "gear-generator")
MODEL_GEAR_CRITIC:str = os.environ.get("MODEL_GEAR_CRITIC","gear-critic")
MODEL_ESCALATION: str = os.environ.get("MODEL_ESCALATION", "gear-escalation")


# ---------------------------------------------------------------------------
# Game defaults (used as fallbacks when guild config is absent)
# ---------------------------------------------------------------------------
DEFAULT_REALM:  str = os.environ.get("DEFAULT_REALM",  "dreamscythe")
DEFAULT_REGION: str = os.environ.get("DEFAULT_REGION", "us")
CURRENT_PHASE:  int = int(os.environ.get("CURRENT_PHASE", "1"))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate() -> list[str]:
    """Return a list of missing required config keys. Empty = all good."""
    missing = []
    if not DISCORD_TOKEN:
        missing.append("DISCORD_BOT_TOKEN")
    if not WCL_CLIENT_ID:
        missing.append("WCL_CLIENT_ID")
    if not WCL_CLIENT_SECRET:
        missing.append("WCL_CLIENT_SECRET")
    return missing
