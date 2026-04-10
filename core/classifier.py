"""
BrnzyBot intent classifier.

Two-stage pipeline:
  1. Deterministic parser — fast, no LLM, handles exact command syntax.
     Returns Intent(confidence=1.0) on success, None on failure.

  2. LLM triage — called only when deterministic parse fails.
     Returns Intent(confidence<1.0) with best-effort params.
     May set clarification if ambiguous.

Callers:
    intent = classify(message_text, guild_id, source="prefix")
    if intent.needs_clarification():
        # store pending, ask user
    elif intent.is_executable():
        # dispatch to handler
    else:
        # drop silently
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from core.intent import Intent

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known spec aliases — maps common shorthands to canonical spec keys
# ---------------------------------------------------------------------------
SPEC_ALIASES: dict[str, str] = {
    # Warlock
    "destro":       "destro_warlock",
    "destruction":  "destro_warlock",
    "afflic":       "affliction_warlock",
    "affliction":   "affliction_warlock",
    "demo":         "demonology_warlock",
    "demonology":   "demonology_warlock",
    # Shaman
    "ele":          "ele_shaman",
    "elemental":    "ele_shaman",
    "enh":          "enh_shaman",
    "enhance":      "enh_shaman",
    "enhancement":  "enh_shaman",
    "resto":        "resto_shaman",
    # Hunter
    "bm":           "bm_hunter",
    "beast":        "bm_hunter",
    "beastmastery": "bm_hunter",
    "mm":           "mm_hunter",
    "marks":        "mm_hunter",
    "marksmanship": "mm_hunter",
    "surv":         "survival_hunter",
    "survival":     "survival_hunter",
    # Mage
    "fire":         "fire_mage",
    "frost":        "frost_mage",
    "arcane":       "arcane_mage",
    # Priest
    "shadow":       "shadow_priest",
    "holy":         "holy_priest",
    # Druid
    "balance":      "balance_druid",
    "boomkin":      "balance_druid",
    "feral":        "feral_cat_druid",
    "bear":         "feral_bear_druid",
    "restod":       "resto_druid",
    # Paladin
    "ret":          "ret_paladin",
    "retrib":       "ret_paladin",
    "retribution":  "ret_paladin",
    "prot":         "prot_paladin",
    "holyp":        "holy_paladin",
    # Warrior
    "fury":         "fury_warrior",
    "arms":         "arms_warrior",
    "protw":        "prot_warrior",
    # Rogue
    "assassin":     "assassination_rogue",
    "assassination":"assassination_rogue",
    "combat":       "combat_rogue",
}

# Prefix/alias forms for each command
COMMAND_PATTERNS: dict[str, list[str]] = {
    "gearprio":   ["gearprio", "gp", "prio"],
    "gearcheck":  ["gearcheck", "gc", "gear"],
    "addchar":    ["addchar", "addcharacter"],
    "removechar": ["removechar", "delchar"],
    "listchars":  ["listchars", "chars", "characters"],
    "verbosity":  ["verbosity", "verbose"],
    "setup":      ["setup"],
    "help":       ["help", "h"],
}

# Build reverse map: alias → canonical command
_CMD_LOOKUP: dict[str, str] = {}
for _cmd, _aliases in COMMAND_PATTERNS.items():
    for _alias in _aliases:
        _CMD_LOOKUP[_alias.lower()] = _cmd


# ---------------------------------------------------------------------------
# Deterministic parser
# ---------------------------------------------------------------------------

def _resolve_spec(token: str) -> Optional[str]:
    return SPEC_ALIASES.get(token.lower())


def parse(text: str, source: str = "unknown") -> Optional[Intent]:
    """
    Attempt deterministic parsing of a command string.

    Handles:
        !gearprio brnz 3
        !gearprio brnz bis
        !gearcheck brnz
        !gearcheck brnz destro
        /gearprio brnz 3   (slash commands pass args as plain text too)
        gearprio brnz 3    (no prefix — used by slash command handler directly)

    Returns Intent(confidence=1.0) on success, None on failure.
    """
    # Strip prefix characters and leading whitespace
    clean = text.strip().lstrip("!/").strip()
    if not clean:
        return None

    parts = clean.split()
    if not parts:
        return None

    cmd_token = parts[0].lower()
    command = _CMD_LOOKUP.get(cmd_token)
    if not command:
        return None

    args = parts[1:]  # everything after the command token

    # --- gearprio ---
    if command == "gearprio":
        character   = None
        mode        = "upgrades"
        max_changes = 3

        for arg in args:
            if arg.isdigit():
                max_changes = max(1, min(int(arg), 17))
            elif arg.lower() == "bis":
                mode = "bis"
            elif character is None:
                character = arg.lower()

        return Intent(
            command="gearprio",
            character=character,
            params={"mode": mode, "max_changes": max_changes},
            confidence=1.0,
            source=source,
            raw_message=text,
        )

    # --- gearcheck ---
    if command == "gearcheck":
        character = None
        spec      = None

        for arg in args:
            maybe_spec = _resolve_spec(arg)
            if maybe_spec:
                spec = maybe_spec
            elif character is None:
                character = arg.lower()

        return Intent(
            command="gearcheck",
            character=character,
            spec=spec,
            confidence=1.0,
            source=source,
            raw_message=text,
        )

    # --- addchar ---
    if command == "addchar":
        # !addchar <name> <spec> [realm] [region]
        if len(args) < 2:
            return None   # not enough info — let triage or slash handle it
        name  = args[0]
        spec  = _resolve_spec(args[1]) or args[1].lower()
        realm = args[2] if len(args) > 2 else None
        region= args[3].lower() if len(args) > 3 else "us"
        return Intent(
            command="addchar",
            character=name.lower(),
            spec=spec,
            params={"display_name": name, "realm": realm, "region": region},
            confidence=1.0,
            source=source,
            raw_message=text,
        )

    # --- removechar / listchars / help / setup / verbosity ---
    if command in ("removechar", "listchars", "help", "setup"):
        character = args[0].lower() if args else None
        return Intent(
            command=command,
            character=character,
            confidence=1.0,
            source=source,
            raw_message=text,
        )

    if command == "verbosity":
        mode = args[0].lower() if args else None
        return Intent(
            command="verbosity",
            params={"mode": mode},
            confidence=1.0,
            source=source,
            raw_message=text,
        )

    return None


# ---------------------------------------------------------------------------
# LLM triage (called only when deterministic parse returns None)
# ---------------------------------------------------------------------------

_TRIAGE_SYSTEM = """\
You are a World of Warcraft gear assistant dispatcher.
Given a player's message, extract their intent as JSON.

Respond ONLY with valid JSON matching this schema:
{
  "command": "gearprio" | "gearcheck" | "unknown",
  "character": string | null,
  "spec": string | null,
  "params": {},
  "confidence": float between 0 and 1,
  "clarification": string | null
}

Commands:
- gearprio: player wants to know what gear upgrades to prioritize
- gearcheck: player wants a full gear analysis or advice on their current gear
- unknown: message is not about gear optimization

For spec, use canonical names like "destro_warlock", "ele_shaman", "bm_hunter".
If the character or spec is ambiguous, set clarification to a short question to ask the user.
If confidence is below 0.6, set command to "unknown".
"""


def triage_with_llm(text: str, source: str = "nl") -> Intent:
    """
    Use local LLM to extract intent from natural language.
    Falls back to Intent.unknown() on any failure.
    """
    try:
        import litellm  # type: ignore
        import config

        response = litellm.completion(
            model=config.MODEL_TRIAGE,
            api_base=config.LITELLM_BASE_URL,
            api_key=config.LITELLM_API_KEY,
            messages=[
                {"role": "system", "content": _TRIAGE_SYSTEM},
                {"role": "user", "content": text},
            ],
            max_tokens=256,
            temperature=0.1,
        )
        raw = response.choices[0].message.content.strip()

        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        data = json.loads(raw)
        return Intent(
            command=data.get("command", "unknown"),
            character=data.get("character"),
            spec=data.get("spec"),
            params=data.get("params") or {},
            confidence=float(data.get("confidence", 0.5)),
            clarification=data.get("clarification"),
            source=source,
            raw_message=text,
        )

    except Exception as exc:
        log.warning("LLM triage failed: %s", exc)
        return Intent.unknown(raw=text, source=source)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def classify(text: str, source: str = "unknown", use_llm: bool = True) -> Intent:
    """
    Classify a message into an Intent.

    1. Try deterministic parse (instant, no LLM).
    2. If that fails and use_llm=True, try LLM triage.
    3. If all else fails, return Intent.unknown().
    """
    # Deterministic first
    intent = parse(text, source=source)
    if intent is not None:
        return intent

    # LLM triage for natural language
    if use_llm:
        log.debug("Deterministic parse failed, trying LLM triage: %r", text[:80])
        return triage_with_llm(text, source=source)

    return Intent.unknown(raw=text, source=source)
