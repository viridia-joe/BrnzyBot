"""
Gem reference data for the audit — authoritative gem color/quality (from WowSims,
via data/gem_db.json) plus meta-gem activation requirements (data/meta_gems.json).

Used by:
  - normalize: resolve a socketed gem's color/quality by id, and identify metas.
  - report.check_meta: evaluate whether a socketed meta gem's color requirement
    is met (compound gems count toward both their colors).

Pure data access; no network, no DB. Missing files degrade to "unknown" (None),
never a crash.
"""

from __future__ import annotations

import json
import os

_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")

# A compound gem counts toward each of its component colors for meta requirements.
COLOR_COMPONENTS = {
    "Red": {"Red"}, "Blue": {"Blue"}, "Yellow": {"Yellow"},
    "Orange": {"Red", "Yellow"}, "Purple": {"Red", "Blue"}, "Green": {"Yellow", "Blue"},
    "Prismatic": {"Red", "Blue", "Yellow"}, "Meta": set(),
}

_GEMS: dict[int, dict] = {}
_META: dict[int, dict] = {}
_loaded = False


def _load() -> None:
    global _GEMS, _META, _loaded
    if _loaded:
        return
    try:
        with open(os.path.join(_DATA, "gem_db.json"), encoding="utf-8-sig") as f:
            _GEMS = {int(k): v for k, v in json.load(f).items()}
    except (FileNotFoundError, ValueError):
        _GEMS = {}
    try:
        with open(os.path.join(_DATA, "meta_gems.json"), encoding="utf-8-sig") as f:
            _META = {int(k): v for k, v in json.load(f).items() if k.isdigit()}
    except (FileNotFoundError, ValueError):
        _META = {}
    _loaded = True


def gem_color(gem_id: int) -> str | None:
    _load()
    g = _GEMS.get(gem_id)
    return g["color"] if g else None


def gem_quality(gem_id: int) -> str | None:
    _load()
    g = _GEMS.get(gem_id)
    return g["quality"] if g else None


def is_meta(gem_id: int) -> bool:
    return gem_color(gem_id) == "Meta"


def meta_requirement(gem_id: int) -> dict | None:
    """{name, require:{color:count}, verified:bool} for a meta gem id, or None."""
    _load()
    return _META.get(gem_id)
