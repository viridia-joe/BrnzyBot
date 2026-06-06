"""
Author canonical fight diagrams (run offline; needs Pillow + the background art).

Composites a real minimap background with a CONSISTENT role-icon set placed per a
per-boss JSON spec, and writes data/diagrams/<boss>.png — which core.fight_diagrams
then serves at runtime with no Pillow needed. Author once, commit the PNG.

Spec file: data/diagrams/<boss>.json
{
  "boss": "gruul",
  "background": "backgrounds/gruuls_lair.png",   # real minimap crop, relative to data/diagrams/
  "title": "Gruul the Dragonkiller",
  "markers": [
    {"role": "boss",   "x": 0.50, "y": 0.45, "label": "Gruul"},
    {"role": "tank",   "x": 0.50, "y": 0.30, "label": "MT"},
    {"role": "melee",  "x": 0.50, "y": 0.58, "label": "Melee"},
    {"role": "ranged", "x": 0.25, "y": 0.72, "label": "Ranged — spread 10yd"},
    {"role": "healer", "x": 0.75, "y": 0.72, "label": "Healers"},
    {"role": "marker", "x": 0.50, "y": 0.86, "label": "Spread for Shatter"}
  ]
}
x/y are fractions of the background (0..1), so placements are resolution-independent.

Usage:
    python -m tools.render_diagrams gruul       # one boss
    python -m tools.render_diagrams --all       # every <boss>.json in data/diagrams/
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.fight_diagrams import DIAGRAM_DIR

# One consistent icon per role, used across EVERY encounter (color + glyph).
ROLE_ICONS = {
    "boss":   ("#7d3c98", "B"),   # purple
    "tank":   ("#3b6fb0", "T"),   # blue
    "healer": ("#3fa45b", "H"),   # green
    "melee":  ("#c0392b", "M"),   # red
    "ranged": ("#e08a1e", "R"),   # orange
    "marker": ("#555555", "*"),   # neutral note/stack point
}
_RADIUS = 16


def _font(size: int):
    from PIL import ImageFont
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/Library/Fonts/Arial.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render(boss_key: str) -> str:
    """Render data/diagrams/<boss_key>.json → data/diagrams/<boss_key>.png. Returns the path."""
    from PIL import Image, ImageDraw

    spec_path = os.path.join(DIAGRAM_DIR, f"{boss_key}.json")
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)

    bg_path = os.path.join(DIAGRAM_DIR, spec["background"])
    bg = Image.open(bg_path).convert("RGBA")
    draw = ImageDraw.Draw(bg)
    w, h = bg.size

    if spec.get("title"):
        draw.text((12, 10), spec["title"], fill="white", font=_font(22))

    for m in spec.get("markers", []):
        color, glyph = ROLE_ICONS.get(m.get("role", "marker"), ROLE_ICONS["marker"])
        cx, cy = int(m["x"] * w), int(m["y"] * h)
        draw.ellipse((cx - _RADIUS, cy - _RADIUS, cx + _RADIUS, cy + _RADIUS),
                     fill=color, outline="white", width=2)
        gf = _font(18)
        gb = draw.textbbox((0, 0), glyph, font=gf)
        draw.text((cx - (gb[2] - gb[0]) // 2, cy - (gb[3] - gb[1]) // 2 - gb[1]),
                  glyph, fill="white", font=gf)
        if m.get("label"):
            draw.text((cx + _RADIUS + 4, cy - 8), m["label"], fill="white", font=_font(14))

    out = os.path.join(DIAGRAM_DIR, f"{boss_key}.png")
    bg.convert("RGB").save(out, "PNG")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Render canonical fight diagrams from JSON specs.")
    ap.add_argument("boss", nargs="?", help="boss key (matches data/diagrams/<boss>.json)")
    ap.add_argument("--all", action="store_true", help="render every spec in data/diagrams/")
    args = ap.parse_args()
    try:
        import PIL  # noqa: F401
    except ImportError:
        sys.exit("Pillow is required to author diagrams: pip install Pillow")

    if args.all:
        specs = [f[:-5] for f in os.listdir(DIAGRAM_DIR) if f.endswith(".json")]
    elif args.boss:
        specs = [args.boss]
    else:
        sys.exit("give a boss key or --all")
    for b in specs:
        print("wrote", render(b))


if __name__ == "__main__":
    main()
