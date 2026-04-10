"""
BrnzyBot Triage — Layer 1 intent classifier.

Classifies Discord messages to determine if they require gear reasoning,
a static lookup, strategy advice, or are general chatter. Does NOT attempt
to answer any question — routing and answer generation are downstream.

The 8B model's only job here is extraction and classification. If it
attempts to answer the gear question, the prompt has failed.

Entry point:
    triage(message) -> TriageResult
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import config

log = logging.getLogger(__name__)

TRIAGE_TIMEOUT = 15  # seconds — 8B should respond fast


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TriageResult:
    intent:          str        # "lookup" | "reasoning" | "strategy" | "chatter"
    character:       str        # character/player name, verbatim from message
    realm:           str        # realm name if mentioned, empty = use server default
    items_mentioned: list       # item names extracted verbatim from message
    slot_mentioned:  str        # gear slot if mentioned (Head, Chest, etc.), else ""
    requires_gear:   bool       # True = needs WCL/cache fetch before answering
    raw_response:    str        # model's raw output (for debugging)
    parse_failed:    bool       # True = fell back to safe defaults

    @property
    def needs_reasoning(self) -> bool:
        return self.intent == "reasoning"

    @property
    def is_gear_question(self) -> bool:
        return self.intent in ("lookup", "reasoning")


def _fallback(message: str, raw: str = "") -> TriageResult:
    """Safe fallback when model output can't be parsed. Treat as reasoning."""
    log.warning("Triage parse failed — defaulting to reasoning. Raw: %r", raw[:200])
    return TriageResult(
        intent="reasoning",
        character="",
        realm="",
        items_mentioned=[],
        slot_mentioned="",
        requires_gear=True,
        raw_response=raw,
        parse_failed=True,
    )


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a classifier for a World of Warcraft Discord bot. Your ONLY job is to
extract structured information from a player's message. You must NOT answer the
question or give gear advice — that is handled by a separate system.

Output valid JSON matching this schema exactly:
{
  "intent": "<lookup|reasoning|strategy|chatter>",
  "character": "<character name or empty string>",
  "realm": "<realm name if mentioned, else empty string>",
  "items_mentioned": ["<item name>", ...],
  "slot_mentioned": "<Head|Neck|Shoulder|Chest|Waist|Legs|Feet|Wrist|Hands|Ring|Trinket|Back|Main Hand|Off Hand|Wand|empty string>"
}

Intent definitions:
  lookup     — asking for a specific fact from gear data (current hit rating,
                what item is in a slot, how many set pieces equipped)
  reasoning  — asking for a recommendation, comparison, or upgrade evaluation
                that requires weighing tradeoffs (should I swap X for Y,
                is this an upgrade, what's the best in slot, how does
                breaking a set bonus affect my stat weights)
  strategy   — asking about boss mechanics, spec rotation, raid composition,
                consumables to use — no gear data lookup needed
  chatter    — greetings, jokes, off-topic, unclear intent

Rules:
- Extract character names as-is. Do not resolve or correct them.
- If a realm is mentioned (e.g. "Brnz on Dreamscythe"), capture it.
- items_mentioned: include both the item the player has AND the item they're
  considering. Extract verbatim; do not paraphrase.
- If no character is mentioned, set character to "".
- Output ONLY the JSON object. No explanation, no markdown, no code fences.
"""


def _build_user_message(message: str) -> str:
    return f"Classify this message:\n\n{message}"


# ---------------------------------------------------------------------------
# LiteLLM call
# ---------------------------------------------------------------------------

def _litellm(messages: list) -> str:
    """POST to LiteLLM OpenAI-compat endpoint. Returns content string."""
    url = f"{config.LITELLM_BASE_URL}/chat/completions"
    payload = {
        "model":       config.OLLAMA_MODEL,   # fast-verdict → llama3.1:8b on Icepick
        "messages":    messages,
        "temperature": 0.0,                    # classification must be deterministic
        "max_tokens":  256,
    }
    headers = {"Content-Type": "application/json"}
    if config.LITELLM_API_KEY:
        headers["Authorization"] = f"Bearer {config.LITELLM_API_KEY}"

    body = json.dumps(payload).encode()
    req  = Request(url, data=body, headers=headers, method="POST")
    with urlopen(req, timeout=TRIAGE_TIMEOUT) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

# Gear slot synonyms — normalize to canonical WCL slot names
_SLOT_ALIASES = {
    "head": "Head", "helm": "Head", "hat": "Head",
    "neck": "Neck", "necklace": "Neck", "amulet": "Neck",
    "shoulder": "Shoulder", "shoulders": "Shoulder", "spaulders": "Shoulder",
    "chest": "Chest", "robe": "Chest", "tunic": "Chest",
    "waist": "Waist", "belt": "Waist",
    "legs": "Legs", "pants": "Legs", "leggings": "Legs",
    "feet": "Feet", "boots": "Feet",
    "wrist": "Wrist", "bracers": "Wrist",
    "hands": "Hands", "gloves": "Hands",
    "ring": "Ring", "finger": "Ring",
    "trinket": "Trinket",
    "back": "Back", "cloak": "Back", "cape": "Back",
    "main hand": "Main Hand", "mainhand": "Main Hand", "weapon": "Main Hand",
    "off hand": "Off Hand", "offhand": "Off Hand", "shield": "Off Hand",
    "wand": "Wand",
}

_VALID_INTENTS = {"lookup", "reasoning", "strategy", "chatter"}


def _parse(raw: str) -> Optional[dict]:
    """Extract JSON from model output. Handles fences and leading/trailing text."""
    # Strip markdown code fences if present
    text = re.sub(r"```(?:json)?\s*", "", raw).strip()

    # Try the full string first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find the first {...} block
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    return None


def _validate_and_build(parsed: dict, raw: str) -> TriageResult:
    """Validate parsed dict and produce a TriageResult with safe defaults."""
    intent = parsed.get("intent", "chatter")
    if intent not in _VALID_INTENTS:
        log.warning("Triage: unknown intent %r, defaulting to reasoning", intent)
        intent = "reasoning"

    slot_raw = parsed.get("slot_mentioned", "")
    slot = _SLOT_ALIASES.get(slot_raw.lower(), slot_raw) if slot_raw else ""

    requires_gear = intent in ("lookup", "reasoning")

    return TriageResult(
        intent=intent,
        character=str(parsed.get("character", "")),
        realm=str(parsed.get("realm", "")),
        items_mentioned=list(parsed.get("items_mentioned", [])),
        slot_mentioned=slot,
        requires_gear=requires_gear,
        raw_response=raw,
        parse_failed=False,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def triage(message: str) -> TriageResult:
    """
    Classify a Discord message and extract gear-relevant entities.

    Returns a TriageResult with intent, character name, and items mentioned.
    On model failure or parse error, returns a safe fallback that routes
    to full reasoning — better to over-route than to silently drop a question.
    """
    messages = [
        {"role": "system",  "content": SYSTEM_PROMPT},
        {"role": "user",    "content": _build_user_message(message)},
    ]

    raw = ""
    try:
        raw = _litellm(messages)
        log.debug("Triage raw response: %r", raw)
    except (URLError, HTTPError, TimeoutError, KeyError, json.JSONDecodeError) as e:
        log.warning("Triage model call failed: %s", e)
        return _fallback(message)

    parsed = _parse(raw)
    if parsed is None:
        return _fallback(message, raw)

    try:
        return _validate_and_build(parsed, raw)
    except Exception as e:
        log.warning("Triage validation error: %s", e)
        return _fallback(message, raw)
