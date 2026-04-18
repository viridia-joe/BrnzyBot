"""
general_handler.py — pipeline for open-ended questions directed at the bot.

Handles questions like:
  "why is Cloak of the Black Void better than Spore-Soaked Vaneer?"
  "how does hit cap work for warlocks in TBC?"
  "what's the stat priority for ele shaman?"

Pipeline:
  1. Try to detect a character name in the question → enrich with gear context
  2. Try to detect a boss/item name → enrich with strategy context
  3. Build a minimal TBC expert prompt
  4. Call Claude via LiteLLM
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

GENERAL_SYSTEM = """\
You are BrnzyBot, a World of Warcraft TBC expert embedded in a raid team's Discord server.
You have a gnomish tinkering pedigree — precise, analytical, and direct.

You answer questions about:
- TBC item stats and comparisons (use EP values if provided in context, otherwise use general knowledge)
- Class mechanics, stat priorities, hit caps, spell coefficients
- Raid strategy and boss mechanics
- Set bonus math, socket bonuses, and gear optimization logic

Tone: Helpful and thorough, but concise. Lead with the answer. Show math when relevant.
If you're given a Gear Context block, use its EP values as ground truth.
If you're given a Strategy Context block, use its mechanic descriptions as ground truth.
If no context is provided, answer from general TBC knowledge and note any uncertainty.

Format: Discord-friendly. Short paragraphs or bullet points. No markdown tables.
"""


def _find_character_name(question: str, guild_id: str) -> dict | None:
    """Check if any registered character name appears in the question."""
    try:
        from db.server_config import list_characters
        chars = list_characters(guild_id)
        q_lower = question.lower()
        for c in chars:
            if c["name_lower"] in q_lower or c["display_name"].lower() in q_lower:
                return c
    except Exception:
        pass
    return None


def _build_gear_context_for_char(char: dict) -> str:
    """Fetch gear context for a registered character."""
    try:
        import sqlite3
        import os
        import config
        from core.gear_cache import get_gear
        from core.gear_context import build_context

        item_db = sqlite3.connect(config.ITEM_DB_PATH) if os.path.exists(config.ITEM_DB_PATH) else None
        try:
            snapshot = get_gear(
                char["display_name"], char["realm"], char["spec"],
                region=char.get("region", "us"), item_db_conn=item_db,
            )
        finally:
            if item_db:
                item_db.close()

        if snapshot is None:
            return ""

        ctx = build_context(snapshot, char["spec"])
        return ctx.to_prompt_block()
    except Exception as e:
        log.warning("Could not build gear context for general QA: %s", e)
        return ""


def _build_strategy_context(question: str) -> str:
    """Try to pull a strategy context block if the question mentions a boss."""
    try:
        from core.strategy_context import get_strategy_context
        block = get_strategy_context(question)
        if "no strategy data found" in block.lower():
            return ""
        return block
    except Exception:
        return ""


def handle_general_question(question: str, guild_id: str = "") -> str:
    """
    Answer an open-ended TBC question directed at the bot.
    Enriches with gear or strategy context when detectable.
    Returns a Discord-ready string.
    """
    context_parts = []

    # Try to find a character context
    if guild_id:
        char = _find_character_name(question, guild_id)
        if char:
            gear_block = _build_gear_context_for_char(char)
            if gear_block:
                context_parts.append(gear_block)
                log.info("General QA: enriched with gear context for %s", char["display_name"])

    # Try to find a strategy context
    strat_block = _build_strategy_context(question)
    if strat_block:
        context_parts.append(strat_block)
        log.info("General QA: enriched with strategy context")

    # Build messages
    user_content_parts = context_parts + [f"**Question:** {question}"]
    messages = [
        {"role": "system", "content": GENERAL_SYSTEM},
        {"role": "user",   "content": "\n\n".join(user_content_parts)},
    ]

    try:
        from core.gear_reasoning import _litellm, ESCALATION_MODEL, ESCALATION_TIMEOUT
        return _litellm(ESCALATION_MODEL, messages, temperature=0.3,
                        timeout=ESCALATION_TIMEOUT)
    except Exception as e:
        log.error("General QA LLM call failed: %s", e)
        return (
            "I ran into a problem processing that question. "
            "My cogitator array is misfiring — try again in a moment."
        )
