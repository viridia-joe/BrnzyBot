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

import difflib
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
    "destro":           "destro_warlock",
    "destruction":      "destro_warlock",
    "afflic":           "affliction_warlock",
    "affliction":       "affliction_warlock",
    "firedestro":       "fire_destro_warlock",
    "fire_destro":      "fire_destro_warlock",
    # Shaman
    "ele":              "ele_shaman",
    "elemental":        "ele_shaman",
    "enh":              "enh_shaman",
    "enhance":          "enh_shaman",
    "enhancement":      "enh_shaman",
    "rsham":            "resto_shaman",
    "restosham":        "resto_shaman",
    "restoshaman":      "resto_shaman",
    # Hunter
    "bm":               "bm_hunter",
    "beast":            "bm_hunter",
    "beastmastery":     "bm_hunter",
    "mm":               "mm_hunter",
    "marks":            "mm_hunter",
    "marksmanship":     "mm_hunter",
    "surv":             "survival_hunter",
    "survival":         "survival_hunter",
    # Mage
    "fire":             "fire_mage",
    "frost":            "frost_mage",
    "arcane":           "arcane_mage",
    # Priest
    "shadow":           "shadow_priest",
    "spriest":          "shadow_priest",
    "shadowpriest":     "shadow_priest",
    "holy":             "holy_priest",
    # Druid
    "balance":          "balance_druid",
    "boomkin":          "balance_druid",
    "boomie":           "balance_druid",
    "boomy":            "balance_druid",
    "feral":            "feral_cat_druid",
    "cat":              "feral_cat_druid",
    "bear":             "feral_bear_druid",
    "guardian":         "feral_bear_druid",
    "tree":             "resto_druid",
    "rdruid":           "resto_druid",
    "restodruid":       "resto_druid",
    "restod":           "resto_druid",
    "restoration":      "resto_druid",   # resto_shaman users should type rsham/restosham
    # Paladin
    "ret":              "ret_paladin",
    "retrib":           "ret_paladin",
    "retribution":      "ret_paladin",
    "prot":             "prot_paladin",
    "holyp":            "holy_paladin",
    "holypal":          "holy_paladin",
    "holypaladin":      "holy_paladin",
    # Warrior
    "fury":             "fury_warrior",
    "arms":             "arms_warrior",
    "protw":            "prot_warrior",
    "tankwarrior":      "prot_warrior",
    # Rogue
    "assassin":         "assassination_rogue",
    "assassination":    "assassination_rogue",
    "combat":           "combat_rogue",
}

# Canonical spec keys that have weight files (accepted for registration).
VALID_SPECS: frozenset[str] = frozenset({
    "affliction_warlock", "arcane_mage", "arms_warrior", "assassination_rogue",
    "balance_druid", "bm_hunter", "combat_rogue", "destro_warlock", "fire_destro_warlock",
    "ele_shaman", "enh_shaman", "feral_bear_druid", "feral_cat_druid",
    "fire_mage", "frost_mage", "fury_warrior", "holy_paladin", "holy_priest",
    "mm_hunter", "prot_paladin", "prot_warrior", "resto_druid", "resto_shaman",
    "ret_paladin", "shadow_priest", "survival_hunter",
})

# Human-readable spec labels grouped by class (for /listspecs output).
SPEC_BY_CLASS: dict[str, list[tuple[str, list[str]]]] = {
    "Druid":   [
        ("balance_druid",    ["balance", "boomkin", "boomie"]),
        ("feral_cat_druid",  ["feral", "cat"]),
        ("feral_bear_druid", ["bear", "guardian"]),
        ("resto_druid",      ["tree", "rdruid", "restod", "restoration"]),
    ],
    "Hunter":  [
        ("bm_hunter",       ["bm", "beast"]),
        ("mm_hunter",       ["mm", "marks"]),
        ("survival_hunter", ["surv", "survival"]),
    ],
    "Mage":    [
        ("arcane_mage", ["arcane"]),
        ("fire_mage",   ["fire"]),
        ("frost_mage",  ["frost"]),
    ],
    "Paladin": [
        ("holy_paladin", ["holyp", "holypal"]),
        ("prot_paladin", ["prot"]),
        ("ret_paladin",  ["ret", "retrib", "retribution"]),
    ],
    "Priest":  [
        ("holy_priest",   ["holy"]),
        ("shadow_priest", ["shadow", "spriest"]),
    ],
    "Rogue":   [
        ("assassination_rogue", ["assassin", "assassination"]),
        ("combat_rogue",        ["combat"]),
    ],
    "Shaman":  [
        ("ele_shaman",   ["ele", "elemental"]),
        ("enh_shaman",   ["enh", "enhance", "enhancement"]),
        ("resto_shaman", ["rsham", "restosham"]),
    ],
    "Warlock": [
        ("affliction_warlock",  ["afflic", "affliction"]),
        ("destro_warlock",      ["destro", "destruction"]),
        ("fire_destro_warlock", ["firedestro", "fire_destro"]),
    ],
    "Warrior": [
        ("arms_warrior", ["arms"]),
        ("fury_warrior", ["fury"]),
        ("prot_warrior", ["protw", "tankwarrior"]),
    ],
}


def fuzzy_suggest_spec(raw: str) -> list[str]:
    """Return up to 3 canonical spec suggestions for an unrecognized input."""
    candidates = list(SPEC_ALIASES.keys()) + list(VALID_SPECS)
    close = difflib.get_close_matches(raw.lower(), candidates, n=5, cutoff=0.45)
    seen: dict[str, None] = {}
    for m in close:
        canon = SPEC_ALIASES.get(m, m)
        if canon in VALID_SPECS:
            seen[canon] = None
        if len(seen) >= 3:
            break
    return list(seen.keys())

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
You are a World of Warcraft TBC dispatcher for a raid-focused Discord bot.
Given a player's message, extract their intent as JSON.

Respond ONLY with valid JSON matching this schema:
{
  "command": "gearprio" | "gearcheck" | "strategy" | "general_qa" | "unknown",
  "character": string | null,
  "spec": string | null,
  "params": {},
  "confidence": float between 0 and 1,
  "clarification": string | null
}

Commands:
- gearprio: player wants to know what gear upgrades to prioritize for a character
- gearcheck: player wants a full gear analysis or review of a character's current gear
- strategy: player is asking about a boss encounter, raid mechanic, spell, or fight strategy
- general_qa: player is asking a general WoW/TBC question — item comparisons, theorycrafting,
              how a mechanic works, stat math, set bonuses, class questions, etc.
              Use this when the question is directed at the bot but doesn't fit the above commands.
- unknown: message is clearly not a WoW-related question

For spec, use canonical names like "destro_warlock", "ele_shaman", "bm_hunter".
If the character or spec is ambiguous, set clarification to a short question to ask the user.
Only use "unknown" if the message has nothing to do with WoW or raiding.
"""


def triage_with_llm(text: str, source: str = "nl") -> Intent:
    """
    Use the configured LLM to extract intent from natural language.
    Talks to the LiteLLM proxy over plain HTTP (OpenAI-compatible) — no heavy
    SDK dependency. Falls back to Intent.unknown() on any failure.
    """
    try:
        import config
        from core import llm

        raw = llm.chat(
            config.MODEL_TRIAGE,
            [{"role": "system", "content": _TRIAGE_SYSTEM},
             {"role": "user", "content": text}],
            temperature=0.1, max_tokens=256, timeout=15,
        ).strip()

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

def classify(text: str, source: str = "unknown", use_llm: bool = True,
             guild_id: str = "global") -> Intent:
    """
    Classify a message into an Intent.

    1. Try deterministic parse (instant, no LLM).
    2. If that fails and use_llm=True and the guild may use the LLM, try triage.
    3. If all else fails, return Intent.unknown().
    """
    # Deterministic first
    intent = parse(text, source=source)
    if intent is not None:
        return intent

    # LLM triage for natural language — only when the model layer is enabled
    # for this guild (Pro). Free/disabled → unknown (deterministic).
    if use_llm:
        from core import entitlements
        if not entitlements.llm_enabled(guild_id):
            log.debug("Deterministic parse failed and LLM off for guild — unknown: %r", text[:80])
            return Intent.unknown(raw=text, source=source)
        log.debug("Deterministic parse failed, trying LLM triage: %r", text[:80])
        intent = triage_with_llm(text, source=source)
        entitlements.note_llm_call(guild_id)
        return intent

    return Intent.unknown(raw=text, source=source)
