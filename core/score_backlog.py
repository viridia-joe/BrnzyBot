"""
Item scoring backlog — items the gear pipeline couldn't fairly EP-score.

Some equipped items have no usable EP (on-use / on-proc trinkets like Quagmirran's
Eye or Eye of Moam, and other phase-0 dungeon/world items). Rather than mis-grade
them, the gear list records them here so they can be reviewed and hand-scored over
time, building a proper proc/trinket value table incrementally.

Append-only JSONL at ~/.openclaw/data/score_backlog.jsonl. Deduped by item_id, so
running /gearcheck repeatedly doesn't bloat it. Review with tools/score_backlog_cli.py.
"""

from __future__ import annotations

import json
import logging
import os

log = logging.getLogger(__name__)

try:
    import config
    _PATH = os.path.join(os.path.dirname(config.BOT_DB_PATH), "score_backlog.jsonl")
except Exception:  # pragma: no cover — config always imports in prod
    _PATH = os.path.expanduser("~/.openclaw/data/score_backlog.jsonl")

_seen_ids: set[int] | None = None


def _load_seen() -> set[int]:
    global _seen_ids
    if _seen_ids is None:
        _seen_ids = set()
        try:
            with open(_PATH, encoding="utf-8") as f:
                for line in f:
                    try:
                        _seen_ids.add(int(json.loads(line)["item_id"]))
                    except (ValueError, KeyError, json.JSONDecodeError):
                        continue
        except FileNotFoundError:
            pass
    return _seen_ids


def record_unscored(item_id: int, name: str, slot: str, spec: str,
                    reason: str = "no EP (likely on-use/proc effect)") -> None:
    """Log one unscored item for later hand-scoring. Deduped by item_id; best-effort
    (never raises into the gear pipeline)."""
    if not item_id:
        return
    seen = _load_seen()
    if item_id in seen:
        return
    try:
        os.makedirs(os.path.dirname(_PATH), exist_ok=True)
        with open(_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "item_id": int(item_id), "name": name, "slot": slot,
                "spec": spec, "reason": reason,
            }) + "\n")
        seen.add(item_id)
        log.info("score_backlog: recorded unscored item %s (%s)", name, item_id)
    except Exception as e:  # disk full / readonly — don't break gearcheck
        log.warning("score_backlog write failed: %s", e)
