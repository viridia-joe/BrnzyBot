"""
Canonical per-encounter fight diagrams.

Serve ONE great, committed diagram per boss instead of redrawing a schematic on
every request. The runtime path needs **no Pillow** — it just reads a committed
PNG (`data/diagrams/<boss_key>.png`). Authoring those PNGs (real minimap
background + a consistent role-icon set placed per the known popular strategy) is
done once, offline, via `tools/render_diagrams.py`, and the result is committed.

`/bossguide` diagram lookup order:
    canonical committed PNG  →  (legacy) procedural generator  →  text only.

Deterministic; no LLM.
"""

from __future__ import annotations

import os

DIAGRAM_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "diagrams"
)


def canonical_path(boss_key: str) -> str:
    return os.path.join(DIAGRAM_DIR, f"{boss_key}.png")


def has_canonical(boss_key: str) -> bool:
    return os.path.exists(canonical_path(boss_key))


def get_canonical(boss_key: str) -> bytes | None:
    """
    The committed canonical diagram for this boss, or None if one hasn't been
    authored yet. Pure file read — safe with no Pillow and on the 1 GB box.
    """
    path = canonical_path(boss_key)
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None
