"""
BrnzyBot Intent — the contract between message parsing and command handlers.

Every inbound path (slash command, prefix command, natural language) produces
an Intent. Command handlers only ever receive an Intent — they never see raw
Discord messages, never know whether the trigger was a slash or a mention.

This decoupling is what eliminates double responses and leaked internals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Known commands
# ---------------------------------------------------------------------------
KNOWN_COMMANDS = {
    "gearprio",    # !gearprio / /gearprio — MIP upgrade optimizer
    "gearcheck",   # !gearcheck / /gearcheck — full gear context + reasoning
    "addchar",     # /addchar — register a character
    "removechar",  # /removechar — deregister a character
    "listchars",   # /listchars — show registered characters
    "setup",       # /setup — configure guild (realm, region, recap channel)
    "verbosity",   # /verbosity — set channel verbosity mode
    "help",        # !help / /help
    "unknown",     # triage couldn't determine intent
}


# ---------------------------------------------------------------------------
# Intent dataclass
# ---------------------------------------------------------------------------

@dataclass
class Intent:
    """
    A parsed, normalized representation of what the user wants.

    Fields:
        command         One of KNOWN_COMMANDS.
        character       Lowercase character name, if supplied.
        spec            Spec key (e.g. "destro_warlock"), if supplied or inferred.
        params          Command-specific params (max_changes, mode, verbosity, etc.)
        confidence      1.0 = deterministic parse. <1.0 = LLM triage estimate.
        clarification   If set, the bot should ask this question before executing.
                        The intent is stored as pending until the user responds.
        source          How this intent was created: "slash" | "prefix" | "mention" | "nl"
        raw_message     Original message text, for logging only. Never used by handlers.
    """
    command:       str
    character:     Optional[str]       = None
    spec:          Optional[str]       = None
    params:        dict                = field(default_factory=dict)
    confidence:    float               = 1.0
    clarification: Optional[str]       = None
    source:        str                 = "unknown"
    raw_message:   str                 = ""

    def needs_clarification(self) -> bool:
        return self.clarification is not None

    def is_executable(self) -> bool:
        return self.command in KNOWN_COMMANDS and self.command != "unknown"

    def to_dict(self) -> dict:
        return {
            "command":       self.command,
            "character":     self.character,
            "spec":          self.spec,
            "params":        self.params,
            "confidence":    self.confidence,
            "clarification": self.clarification,
            "source":        self.source,
            "raw_message":   self.raw_message,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Intent":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    @classmethod
    def unknown(cls, raw: str = "", source: str = "unknown") -> "Intent":
        return cls(command="unknown", raw_message=raw, source=source, confidence=0.0)


# ---------------------------------------------------------------------------
# TriageResult — moved here from core/triage.py (legacy Ollama classifier)
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
