"""
Boss guide data — loaded from the unified strategy store (`data/strategy/*.json`).

This module used to hardcode every boss as a Python dict. Boss content now lives
in one place: each boss in a strategy file may carry an optional ``bossguide``
block, and this module loads those into ``BossEntry`` objects at import. That
keeps /strat (FTS over the same files) and /bossguide reading a single source of
truth, and lets new raids be added as data rather than code.

A boss participates in /bossguide iff its strategy entry has a ``bossguide`` block:

    {
      "name": "Hydross the Unstable", "slug": "hydross",
      ...strat fields...,
      "bossguide": {
        "boss_num": 1, "raid_short": "SSC", "has_diagram": true,
        "aliases": ["hydross", "hyd"],
        "role_counts": {"tanks": 3, ...},
        "context": "FIGHT: ..."        # injected into Claude's assignment prompt
      }
    }

Public API (unchanged): ``BossEntry``, ``BOSS_DATA``, ``resolve_boss``,
``BOSS_DISPLAY_ORDER``. The boss key is the strategy ``slug`` (also the key
fight diagrams are stored under, e.g. ``data/diagrams/hydross.png``).
"""

from __future__ import annotations

import glob
import json
import logging
import os
from dataclasses import dataclass
from typing import Dict, List, Tuple

import config

log = logging.getLogger(__name__)


@dataclass
class BossEntry:
    full_name: str
    raid: str
    boss_num: int
    has_diagram: bool
    aliases: List[str]
    context: str
    roles: Dict[str, int]  # role label -> count hint


def _load() -> Tuple[Dict[str, BossEntry], List[Tuple[str, str]]]:
    """Scan the strategy data dir and build BOSS_DATA + display order from any
    boss carrying a ``bossguide`` block. Ordered by (content_phase, raid, boss#)."""
    data: Dict[str, BossEntry] = {}
    order: List[Tuple[int, str, int, str, str]] = []

    pattern = os.path.join(config.STRATEGY_DATA_DIR, "*.json")
    for path in sorted(glob.glob(pattern)):
        try:
            with open(path, encoding="utf-8-sig") as f:
                zone = json.load(f)
        except (OSError, ValueError) as e:
            log.warning("bossguide_data: skipping %s (%s)", os.path.basename(path), e)
            continue

        phase = zone.get("_meta", {}).get("content_phase",
                                          zone.get("_meta", {}).get("phase", 1))
        for boss in zone.get("bosses", []):
            bg = boss.get("bossguide")
            if not bg:
                continue
            key = boss["slug"]
            raid_short = bg.get("raid_short", "")
            boss_num = bg.get("boss_num", 0)
            data[key] = BossEntry(
                full_name=boss["name"],
                raid=raid_short,
                boss_num=boss_num,
                has_diagram=bool(bg.get("has_diagram", False)),
                aliases=list(bg.get("aliases", [])),
                context=bg.get("context", ""),
                roles=dict(bg.get("role_counts", {})),
            )
            order.append((phase, raid_short, boss_num, key, boss["name"]))

    order.sort()
    display = [(key, name) for _phase, _raid, _num, key, name in order]
    if not data:
        log.warning("bossguide_data: no bossguide blocks found under %s", pattern)
    return data, display


BOSS_DATA, BOSS_DISPLAY_ORDER = _load()

# Alias -> canonical key lookup
_ALIAS_MAP: Dict[str, str] = {}
for _key, _entry in BOSS_DATA.items():
    for _alias in _entry.aliases:
        _ALIAS_MAP[_alias.lower()] = _key


def resolve_boss(name: str) -> str | None:
    """Return canonical boss key for a given name/alias, or None if not found."""
    normalized = name.lower().strip()
    if normalized in BOSS_DATA:
        return normalized
    if normalized in _ALIAS_MAP:
        return _ALIAS_MAP[normalized]
    # Partial substring match
    for alias, key in _ALIAS_MAP.items():
        if normalized in alias or alias in normalized:
            return key
    return None
