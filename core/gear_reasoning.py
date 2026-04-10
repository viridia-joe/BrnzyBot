"""
BrnzyBot Gear Reasoning — Layer 3/4 generator-critic loop.

Architecture:
  1. Post thinking message immediately (non-blocking flavor text).
  2. Generator (gear-generator → deepseek-r1:32b, Tomahawk P1 → Cudgel P2)
     produces a full gear analysis with chain-of-thought.
  3. Critic (gear-critic → deepseek-r1:32b, Cudgel P1 → Tomahawk P2)
     evaluates the generator's answer against the pre-computed context.
  4. If confidence >= 7: post answer.
     If confidence 5-6: post answer with uncertainty note.
     If confidence < 5: give generator one retry with critic's issues.
  5. If second attempt also rejected, or only one 32B node is available:
     escalate to Claude via LiteLLM (config.CLAUDE_MODEL).

Entry points:
    reason(context, triage_result, message, post_fn, node_status) -> str
"""

import json
import logging
import random
import re
from dataclasses import dataclass
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

import config
from gear_context import GearContext
from triage import TriageResult

log = logging.getLogger(__name__)

GENERATOR_MODEL  = "gear-generator"
CRITIC_MODEL     = "gear-critic"
ESCALATION_MODEL = "gear-escalation"   # LiteLLM route → Claude Opus via Anthropic API
REASONING_TIMEOUT  = 360   # 6 min — 32B on 4090 w/ partial CPU offload is slow
CRITIQUE_TIMEOUT   = 240   # 4 min
ESCALATION_TIMEOUT = 90    # Claude is fast

CONFIDENCE_POST_WITH_WARNING = 5   # 5–6: post with uncertainty note
CONFIDENCE_ACCEPT            = 7   # 7+: post cleanly


# ---------------------------------------------------------------------------
# Thinking messages
# ---------------------------------------------------------------------------

THINKING_MESSAGES = [
    "Calculating... my actuators are spinning.",
    "One moment — cross-referencing the Tomes of Optimal Destruction.",
    "Running the numbers. My differential gear is engaged.",
    "Consulting the Gnomish Theorycraft Engine. Please stand by.",
    "My cogitator array is processing your query. Standby for output.",
]

UNCERTAINTY_SUFFIX = "\n\n*— not fully certain, check my math*"


def thinking_message() -> str:
    return random.choice(THINKING_MESSAGES)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CriticVerdict:
    verdict:    str      # "approved" | "revise" | "reject"
    issues:     list     # list of strings describing problems
    confidence: int      # 0–10


def _fallback_verdict() -> CriticVerdict:
    """Safe fallback if critic output can't be parsed."""
    return CriticVerdict(verdict="revise", issues=["Critic response could not be parsed."], confidence=0)


# ---------------------------------------------------------------------------
# LiteLLM call
# ---------------------------------------------------------------------------

def _litellm(model: str, messages: list, temperature: float = 0.3,
             timeout: int = REASONING_TIMEOUT) -> str:
    url = f"{config.LITELLM_BASE_URL}/chat/completions"
    payload = {
        "model":       model,
        "messages":    messages,
        "temperature": temperature,
        "max_tokens":  1024,   # cap output — gear answers don't need to be long
    }
    headers = {"Content-Type": "application/json"}
    if config.LITELLM_API_KEY:
        headers["Authorization"] = f"Bearer {config.LITELLM_API_KEY}"

    body = json.dumps(payload).encode()
    req  = Request(url, data=body, headers=headers, method="POST")
    with urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Generator prompt
# ---------------------------------------------------------------------------

GENERATOR_SYSTEM = """\
You are BrnzyBot, a World of Warcraft gear advisor for a TBC (The Burning Crusade)
Anniversary raid team. You are a fire robot with a gnomish tinkering pedigree —
precise, dry, and slightly menacing. You take gear math seriously.

You will be given a pre-computed Gear Context block. This block contains facts
that have already been calculated: hit cap status, active set bonuses, and per-item
EP values. YOU MUST NOT re-derive these values. Treat them as ground truth.

Critical rules you must never violate:
1. Hit over cap is worth ZERO EP. If the context says the character is overcapped,
   do not recommend hit items.
2. If a swap would break a set bonus, subtract the set bonus EP from the raw item
   gain. The context block shows the cost of breaking each set.
3. Never mix expansion constants. Everything here is TBC.
4. Be honest about uncertainty. If you're not sure, say so.
5. Show your math. State the EP values, the set bonus costs, and the net gain.

Format: Discord-friendly. Short sentences. No markdown tables. Bullet points OK.
Keep the answer under 300 words unless the question requires more.
"""


def _generator_prompt(context_block: str, question: str,
                      critic_issues: list = None) -> list:
    user_parts = [context_block, "", f"**Question:** {question}"]
    if critic_issues:
        user_parts += [
            "",
            "**A previous attempt at this answer had the following problems.**",
            "Correct these issues in your response:",
        ]
        for issue in critic_issues:
            user_parts.append(f"- {issue}")

    return [
        {"role": "system", "content": GENERATOR_SYSTEM},
        {"role": "user",   "content": "\n".join(user_parts)},
    ]


# ---------------------------------------------------------------------------
# Critic prompt
# ---------------------------------------------------------------------------

CRITIC_SYSTEM = """\
You are a gear math reviewer for a World of Warcraft TBC raid bot. You verify
that gear answers are logically correct given the pre-computed context.

Review the answer against the context. Check for:
1. Hit cap violations — did the answer recommend hit items when the character
   is at or over cap? Hit over cap is worth ZERO EP, not less.
2. Set bonus math — if a swap breaks a set bonus, did the answer account for the
   EP lost? The context shows the cost of breaking each set.
3. Factual errors — does the answer contradict the gear context?
4. Missing context — did the answer ignore important constraints?

Output JSON only. No explanation outside the JSON.
{
  "verdict": "<approved|revise|reject>",
  "issues":  ["<issue 1>", ...],
  "confidence": <0-10>
}

Verdicts:
  approved  — answer is correct, confidence >= 7
  revise    — answer is mostly right but has fixable issues, confidence 5-6
  reject    — answer has a fundamental error, confidence < 5

Empty issues list is fine for approved. Be specific in issues for revise/reject.
"""


def _critic_prompt(context_block: str, question: str, answer: str) -> list:
    return [
        {"role": "system", "content": CRITIC_SYSTEM},
        {"role": "user",   "content": "\n".join([
            context_block,
            "",
            f"**Question:** {question}",
            "",
            f"**Answer to review:**\n{answer}",
        ])},
    ]


def _parse_verdict(raw: str) -> CriticVerdict:
    text = re.sub(r"```(?:json)?\s*", "", raw).strip()

    parsed = None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                parsed = json.loads(m.group(0))
            except json.JSONDecodeError:
                pass

    if not parsed:
        log.warning("Critic output not parseable: %r", raw[:300])
        return _fallback_verdict()

    verdict = parsed.get("verdict", "revise")
    if verdict not in ("approved", "revise", "reject"):
        verdict = "revise"

    return CriticVerdict(
        verdict=verdict,
        issues=list(parsed.get("issues", [])),
        confidence=int(parsed.get("confidence", 0)),
    )


# ---------------------------------------------------------------------------
# Escalation to Claude
# ---------------------------------------------------------------------------

def _escalate(context_block: str, question: str,
              attempt: str = "", critic_issues: list = None) -> str:
    """Fall back to Claude when local nodes can't produce a confident answer."""
    log.info("Escalating gear question to Claude (%s)", ESCALATION_MODEL)
    parts = [context_block, "", f"**Question:** {question}"]
    if attempt:
        parts += ["", "A local model attempted this answer but was flagged:", attempt]
    if critic_issues:
        parts += ["", "Specifically, the reviewer noted:"]
        parts += [f"- {i}" for i in critic_issues]

    messages = [
        {"role": "system", "content": GENERATOR_SYSTEM},
        {"role": "user",   "content": "\n".join(parts)},
    ]
    try:
        return _litellm(ESCALATION_MODEL, messages, temperature=0.2,
                        timeout=ESCALATION_TIMEOUT)
    except Exception as e:
        log.error("Claude escalation failed: %s", e)
        return (
            "My cogitator array encountered an unrecoverable fault. "
            "I cannot produce a confident answer right now. "
            "Please try again later or ask a meatbag theorycrafter."
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def reason(
    context: GearContext,
    triage: TriageResult,
    message: str,
    post_fn,
    node_status=None,
) -> str:
    """
    Run the full generator-critic loop for a gear question.

    Args:
        context:     Pre-computed GearContext (must be built before this call).
        triage:      TriageResult from Layer 1.
        message:     Original Discord message text.
        post_fn:     Callable(str) — posts a message to Discord. Used for
                     the thinking message. Should be non-blocking if possible.
        node_status: Optional NodeStatus from node_health.py. When provided,
                     single-node mode skips critic and escalates directly.

    Returns:
        The final answer string, ready to post to Discord.
    """
    # Post thinking message immediately — 32B takes time
    post_fn(thinking_message())

    context_block = context.to_prompt_block()
    question      = message

    # Check if we have two independent 32B nodes for the full loop.
    # node_status is a NodeStatus dataclass from node_health.py.
    single_node_mode = False
    if node_status is not None:
        available_32b = [n for n in ["tomahawk", "cudgel"]
                         if n in node_status.available]
        if len(available_32b) < 2:
            log.info("Only %d 32B node(s) available (%s) — skipping critic loop",
                     len(available_32b), available_32b)
            single_node_mode = True

    # Claude is the generator. Always. deepseek-r1:32b's chain-of-thought
    # reasoning takes 60-130s per question at 15 tok/s on a 4090 — too slow
    # for Discord. Claude answers in 10-20s and has the pre-computed context.
    #
    # Local 32B is used ONLY as the critic (fast JSON verdict, no CoT needed).
    # If both nodes are unavailable even for the critic, post the Claude answer
    # directly without a critic pass.
    log.info("Routing to Claude (primary generator)")
    first_answer = _escalate(context_block, question)
    if not first_answer or "unrecoverable fault" in first_answer:
        return first_answer

    # ── Critic pass (local 32B for fast JSON verdict) ──────────────────────
    if single_node_mode:
        log.info("No 32B nodes for critic — posting Claude answer directly")
        return first_answer

    # ── Critic pass (local 32B — fast JSON verdict only) ───────────────────
    try:
        crit_msgs = _critic_prompt(context_block, question, first_answer)
        crit_raw  = _litellm(CRITIC_MODEL, crit_msgs, temperature=0.0,
                             timeout=CRITIQUE_TIMEOUT)
        verdict = _parse_verdict(crit_raw)
        log.info("Critic verdict: %s (confidence %d)", verdict.verdict, verdict.confidence)
    except (URLError, HTTPError, TimeoutError, KeyError, json.JSONDecodeError) as e:
        log.warning("Critic call failed: %s — posting Claude answer directly", e)
        return first_answer

    if verdict.confidence >= CONFIDENCE_ACCEPT:
        return first_answer

    # Critic found issues — append uncertainty note but still post.
    # Claude answered with full context; a critic rejection is a signal to
    # check the math, not to discard the answer.
    log.info("Critic confidence %d — appending uncertainty note", verdict.confidence)
    return first_answer + UNCERTAINTY_SUFFIX
