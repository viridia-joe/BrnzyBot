"""
Entitlements — the single gate for paid (LLM-backed) features.

`llm_enabled(guild_id)` is what every LLM site checks instead of the bare
`config.ENABLE_LLM`. It is True only when:

  1. the instance has an LLM backend wired (`config.ENABLE_LLM`), AND
  2. the guild is on the Pro plan (`db.server_config.is_pro`), AND
  3. the guild is under its monthly LLM-call cap (cost defense-in-depth).

Safety property: when `ENABLE_LLM` is false (current prod default), this always
returns False — so every gate behaves exactly as before until an LLM backend is
turned on. Internal callers without a guild context pass "global", which keeps
the pre-Pro behavior (ENABLE_LLM only) so nothing breaks during incremental
rollout.

Subscribing flips a guild to Pro (Stripe webhook → upsert_subscription); that is
all it takes to "turn the LLM features on" for that guild.
"""

from __future__ import annotations

import config
from db.server_config import count_command_month, is_pro, log_usage

# Per-guild LLM-backed calls per month before we stop enhancing (and fall back to
# the deterministic output). Generous — this is a runaway-cost backstop, not a
# product limit. Tune as real usage data comes in.
PRO_LLM_MONTHLY_CAP = 3000

_LLM_USAGE_COMMAND = "llm"
_GLOBAL = ("", "global", None)


def llm_enabled(guild_id: str | None = "global") -> bool:
    """Whether LLM enhancement is allowed for this guild right now."""
    if not config.ENABLE_LLM:
        return False
    if guild_id in _GLOBAL:
        return True  # unknown-guild internal caller → pre-Pro behavior (backend on)
    if not is_pro(guild_id):
        return False
    return count_command_month(guild_id, _LLM_USAGE_COMMAND) < PRO_LLM_MONTHLY_CAP


def note_llm_call(guild_id: str | None = "global") -> None:
    """Record one LLM-backed call for the monthly cap (best-effort)."""
    if guild_id in _GLOBAL:
        return
    try:
        log_usage(guild_id, "system", _LLM_USAGE_COMMAND)
    except Exception:  # metering must never break a user-facing command
        pass
