"""
strategy_handler.py — pipeline entry point for strategy questions.

Entry point for cogs/strategy.py (via handle_strategy_question).
Returns a string — never posts to Discord directly.

Pipeline:
  strategy_context (DB lookup + deterministic render)
  → if ENABLE_LLM: Claude narrates the context block via LiteLLM
    else:          return the deterministic context block directly
  → str
"""

import logging

import config
from core.strategy_context import get_strategy_context

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


def _render_deterministic(context_block: str) -> str:
    """
    Turn the strategy context block into a Discord-ready answer without a model.
    The block is already structured markdown (Discord renders ## headers), so we
    just strip the prompt-oriented "Strategy Context:" framing from the title.
    """
    return context_block.replace("## Strategy Context: ", "## ", 1)


def handle_strategy_question(question: str, guild_id: str = "global") -> str:
    """
    Run the strategy pipeline for a given question.
    Returns a Discord-ready string. Never posts anything itself.
    """
    from core import entitlements
    context_block = get_strategy_context(question)
    log.info("Strategy context fetched for query: %s", question[:60])

    if "no strategy data found" in context_block.lower():
        return (
            f"I don't have strategy data for that in my knowledge base yet. "
            "Currently I cover: **Karazhan**, **Gruul's Lair**, and **Magtheridon**."
        )

    # Deterministic mode: the strategy context block is already a complete,
    # human-readable boss writeup (summary, phases, abilities, strategy variants,
    # role notes). Return it directly instead of having a model narrate it.
    if not entitlements.llm_enabled(guild_id):
        return _render_deterministic(context_block)

    prompt_parts = [context_block, "", f"**Question:** {question}"]
    messages = [
        {"role": "system", "content": STRATEGY_SYSTEM},
        {"role": "user",   "content": "\n".join(prompt_parts)},
    ]

    try:
        from core.gear_reasoning import _litellm, ESCALATION_MODEL, ESCALATION_TIMEOUT
        answer = _litellm(ESCALATION_MODEL, messages, temperature=0.2,
                          timeout=ESCALATION_TIMEOUT)
        entitlements.note_llm_call(guild_id)
        return answer
    except Exception as e:
        log.error("Strategy LLM call failed: %s", e)
        return (
            "I ran into a problem retrieving that strategy. "
            "My cogitator array is misfiring. Try again in a moment."
        )
