"""
strategy_handler.py — pipeline entry point for strategy questions.

Entry point for cogs/strategy.py (via handle_strategy_question).
Returns a string — never posts to Discord directly.

Pipeline:
  strategy_context (DB lookup + deterministic render)
  → gear_reasoning._escalate (Claude with context as ground truth)
  → str
"""

import logging

from core.strategy_context import get_strategy_context
from core.gear_reasoning import _escalate, GENERATOR_SYSTEM
from core.node_health import check_nodes

log = logging.getLogger(__name__)

STRATEGY_SYSTEM = """\
You are BrnzyBot, a World of Warcraft TBC raid strategy advisor.
You have a gnomish tinkering pedigree — precise, methodical, and practical.

You will be given a pre-computed Strategy Context block containing structured
data about a boss encounter: phases, abilities, strategy variants, and role notes.
Treat this block as ground truth. Do not invent mechanics not listed in the context.

When answering:
- Lead with the most important thing to know (usually the wipe mechanic).
- Mention key abilities by name with a brief explanation of what the mechanic does.
- Include role-specific notes when relevant to the question.
- If multiple strategy variants exist, mention which is standard and briefly note alternatives.
- Be practical and specific. Raid members reading this need actionable information.
- If the context block says 'no data found', say so clearly rather than guessing.

Format: Discord-friendly. Short sentences. Bullet points OK. No markdown tables.
Keep answers under 400 words unless the question requires detail across multiple phases.
"""


def handle_strategy_question(question: str) -> str:
    """
    Run the strategy pipeline for a given question.
    Returns a Discord-ready string. Never posts anything itself.
    """
    context_block = get_strategy_context(question)
    log.info("Strategy context fetched for query: %s", question[:60])

    if "no strategy data found" in context_block.lower():
        return (
            f"I don't have strategy data for that in my knowledge base yet. "
            "Currently I cover: **Karazhan**, **Gruul's Lair**, and **Magtheridon**."
        )

    node_status = check_nodes(post_alerts=False)

    prompt_parts = [context_block, "", f"**Question:** {question}"]
    messages = [
        {"role": "system", "content": STRATEGY_SYSTEM},
        {"role": "user",   "content": "\n".join(prompt_parts)},
    ]

    try:
        from core.gear_reasoning import _litellm, ESCALATION_MODEL, ESCALATION_TIMEOUT
        answer = _litellm(ESCALATION_MODEL, messages, temperature=0.2,
                          timeout=ESCALATION_TIMEOUT)
        return answer
    except Exception as e:
        log.error("Strategy LLM call failed: %s", e)
        return (
            "I ran into a problem retrieving that strategy. "
            "My cogitator array is misfiring. Try again in a moment."
        )
