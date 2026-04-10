"""
BrnzyBot Feedback — Layer 5 signal capture.

Two feedback channels:

  Emoji reactions (low friction, pattern detection over time):
    👍  → log positive signal to feedback.jsonl
    👎  → log negative signal to feedback.jsonl
    No individual emoji triggers a rule change. Weekly summarization pass
    reviews patterns and promotes them to gear_rulings.md manually.

  Reply corrections (high friction, high signal):
    The bot watches for @BrnzyBot replies in thread on its own messages.
    Negation patterns ("actually", "wrong", "no", "that's not", "incorrect")
    trigger a confirmation prompt. On confirmation, the correction is extracted
    and appended to gear_rulings.md as a Q/A ruling.
    All guild members are trusted equally — corrections average out over time.

Entry points:
    log_interaction(entry: FeedbackEntry) -> None
    log_emoji(message_id, emoji, direction) -> None
    handle_correction(message_id, correction_text, confirmer) -> str | None
    confirm_ruling(message_id) -> str | None   # call after user replies "yes"
"""

import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)

FEEDBACK_LOG  = os.path.expanduser("~/.openclaw/data/feedback.jsonl")
RULINGS_PATH  = os.path.expanduser("~/.openclaw/workspace/gear_rulings.md")
PENDING_DIR   = os.path.expanduser("~/.openclaw/data/pending_rulings")

# Negation patterns that indicate a correction
_CORRECTION_PATTERNS = re.compile(
    r"\b(actually|wrong|no[,.]|that'?s not|incorrect|not right|"
    r"that is wrong|you're wrong|you are wrong|wait no|hold on)\b",
    re.IGNORECASE,
)

# Acknowledgement phrases — what BrnzyBot says after a correction is confirmed
_ACK_MESSAGES = [
    "Noted. Updating my spellwork reference.",
    "Recalibrating. Thank you for the correction.",
    "Logged. My differential gear appreciates the calibration.",
]

_CONFIRMATION_PROMPT = (
    "Noted — should I remember this ruling for future questions? "
    "Reply **yes** to confirm."
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FeedbackEntry:
    message_id:   str         # Discord message ID of the bot's answer
    timestamp:    int         # Unix seconds
    character:    str         # character the question was about
    spec:         str         # spec key (e.g. "warlock_destro")
    question:     str         # original Discord message
    answer:       str         # bot's answer (truncated to 1000 chars in log)
    confidence:   int         # critic's final confidence score (0 = unknown)
    model_path:   str         # "generator+critic", "generator+critic+claude", etc.
    reaction:     str = ""    # "positive", "negative", or ""


@dataclass
class PendingRuling:
    message_id:     str       # message ID of the bot's answer being corrected
    correction_text: str      # the user's correction message
    corrector:      str       # Discord username who sent the correction
    question:       str       # original question
    answer:         str       # bot's original answer
    timestamp:      int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_dirs():
    for p in (FEEDBACK_LOG, RULINGS_PATH, PENDING_DIR):
        os.makedirs(os.path.dirname(p), exist_ok=True)
    os.makedirs(PENDING_DIR, exist_ok=True)


def _pending_path(message_id: str) -> str:
    return os.path.join(PENDING_DIR, f"{message_id}.json")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Feedback log
# ---------------------------------------------------------------------------

def log_interaction(entry: FeedbackEntry) -> None:
    """Append a new interaction record to feedback.jsonl."""
    _ensure_dirs()
    record = asdict(entry)
    record["answer"] = entry.answer[:1000]  # cap size in log

    with open(FEEDBACK_LOG, "a") as f:
        f.write(json.dumps(record) + "\n")
    log.debug("Logged interaction for message_id=%s", entry.message_id)


def log_emoji(message_id: str, emoji: str, direction: str) -> None:
    """
    Update the reaction field on an existing feedback.jsonl entry.

    If the message_id isn't found (e.g. old interaction), appends a
    stub record so the signal isn't lost.
    """
    _ensure_dirs()
    if emoji not in ("👍", "👎"):
        return
    direction = "positive" if emoji == "👍" else "negative"

    lines = []
    updated = False

    try:
        with open(FEEDBACK_LOG) as f:
            for line in f:
                record = json.loads(line)
                if record.get("message_id") == message_id and not updated:
                    record["reaction"] = direction
                    updated = True
                lines.append(json.dumps(record))
    except FileNotFoundError:
        pass

    if updated:
        with open(FEEDBACK_LOG, "w") as f:
            f.write("\n".join(lines) + "\n")
        log.debug("Updated reaction %s on message_id=%s", direction, message_id)
    else:
        # Stub — we have the signal even without the original record
        stub = {
            "message_id": message_id,
            "timestamp":  int(time.time()),
            "reaction":   direction,
            "stub":       True,
        }
        with open(FEEDBACK_LOG, "a") as f:
            f.write(json.dumps(stub) + "\n")


# ---------------------------------------------------------------------------
# Correction detection
# ---------------------------------------------------------------------------

def is_correction(message_text: str) -> bool:
    """Return True if the message looks like a correction to a bot answer."""
    return bool(_CORRECTION_PATTERNS.search(message_text))


def handle_correction(
    bot_message_id: str,
    correction_text: str,
    corrector: str,
    question: str,
    answer: str,
) -> str:
    """
    Called when a reply to a bot message looks like a correction.

    Saves a pending ruling to disk and returns the confirmation prompt
    the bot should send in reply.
    """
    _ensure_dirs()
    pending = PendingRuling(
        message_id=bot_message_id,
        correction_text=correction_text,
        corrector=corrector,
        question=question,
        answer=answer,
        timestamp=int(time.time()),
    )
    with open(_pending_path(bot_message_id), "w") as f:
        json.dump(asdict(pending), f, indent=2)
    log.info("Pending ruling saved for message_id=%s from %s", bot_message_id, corrector)
    return _CONFIRMATION_PROMPT


def confirm_ruling(bot_message_id: str) -> Optional[str]:
    """
    Called when the user replies "yes" to confirm a correction.

    Loads the pending ruling, formats it, appends to gear_rulings.md,
    removes the pending file, and returns the acknowledgement message.
    Returns None if no pending ruling is found.
    """
    path = _pending_path(bot_message_id)
    if not os.path.exists(path):
        log.warning("confirm_ruling: no pending ruling for message_id=%s", bot_message_id)
        return None

    with open(path) as f:
        data = json.load(f)

    _append_ruling(
        question=data["question"],
        correction=data["correction_text"],
        corrector=data["corrector"],
        original_answer=data["answer"],
    )

    os.remove(path)
    log.info("Ruling confirmed and saved from %s", data["corrector"])

    import random
    return random.choice(_ACK_MESSAGES)


# ---------------------------------------------------------------------------
# Gear rulings
# ---------------------------------------------------------------------------

def _append_ruling(question: str, correction: str, corrector: str,
                   original_answer: str) -> None:
    """
    Append a confirmed correction to gear_rulings.md as a Q/A pair.

    Each entry is formatted as a few-shot example for injection into
    future gear reasoning prompts.
    """
    _ensure_dirs()

    # Truncate for readability in the prompt
    q = question[:300].strip()
    a = correction[:600].strip()

    entry = "\n".join([
        "",
        "## Ruling",
        f"Q: {q}",
        f"A: {a}",
        f"Added: {_today()}  Source: {corrector}",
    ])

    with open(RULINGS_PATH, "a") as f:
        f.write(entry + "\n")
    log.info("Ruling appended to %s", RULINGS_PATH)


def get_rulings() -> str:
    """Return current contents of gear_rulings.md, empty string if none."""
    if not os.path.exists(RULINGS_PATH):
        return ""
    with open(RULINGS_PATH) as f:
        return f.read().strip()
