"""
bossguide_diagram.py — PNG position diagram generator for SSC/TK bosses.

Uses Pillow to draw simple top-down maps. Returns PNG bytes or None if the
boss has no positioning diagram.

Color palette matches the HTML reference file (dark panel + accent colors).
"""

from __future__ import annotations

import io
import os
from typing import Optional

try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False


# ---------------------------------------------------------------------------
# Color constants
# ---------------------------------------------------------------------------
BG          = (14,  16,  21)
PANEL       = (26,  29,  36)
PANEL2      = (35,  39,  48)
INK         = (216, 222, 233)
MUTED       = (138, 147, 163)
GOLD        = (226, 183, 112)
GREEN       = (106, 190, 106)
RED         = (217, 101, 101)
BLUE        = (109, 179, 232)
PURPLE      = (169, 135, 217)
FROST       = (26,  53,  80)
FROST_B     = (58,  96,  128)
FROST_T     = (143, 200, 236)
NATURE      = (31,  58,  26)
NATURE_B    = (90,  128, 64)
NATURE_T    = (168, 212, 136)
ORANGE      = (204, 136, 68)
WHITE       = (255, 255, 255)
DARK        = (17,  20,  26)


# ---------------------------------------------------------------------------
# Font helpers
# ---------------------------------------------------------------------------

def _font(size: int) -> "ImageFont.FreeTypeFont | ImageFont.ImageFont":
    if not _PIL_AVAILABLE:
        return None
    font_candidates = [
        os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", "consola.ttf"),
        os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", "arial.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
    ]
    for path in font_candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Drawing primitives
# ---------------------------------------------------------------------------

def _text_center(draw: "ImageDraw.ImageDraw", cx: int, cy: int, text: str,
                 font, color: tuple) -> None:
    """Draw text centered on (cx, cy)."""
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((cx - w // 2, cy - h // 2), text, fill=color, font=font)


def _dot(draw: "ImageDraw.ImageDraw", cx: int, cy: int, r: int,
         fill: tuple, border: tuple, label: str, sublabel: str,
         font_sm, font_xs) -> None:
    """Draw a colored dot with label below."""
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill, outline=border, width=2)
    if label:
        _text_center(draw, cx, cy + r + 9, label, font_sm, fill)
    if sublabel:
        _text_center(draw, cx, cy + r + 20, sublabel, font_xs, MUTED)


def _boss_circle(draw: "ImageDraw.ImageDraw", cx: int, cy: int, r: int,
                 fill: tuple, border: tuple, label: str, font_md) -> None:
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill, outline=border, width=2)
    _text_center(draw, cx, cy, label, font_md, WHITE)


def _zone_rect(draw: "ImageDraw.ImageDraw", x1: int, y1: int, x2: int, y2: int,
               fill: tuple, border: tuple, label: str, font_sm) -> None:
    draw.rectangle((x1, y1, x2, y2), fill=fill, outline=border, width=1)
    if label:
        draw.text((x1 + 8, y1 + 8), label, fill=border, font=font_sm)


def _dashed_line(draw: "ImageDraw.ImageDraw", x1: int, y1: int, x2: int, y2: int,
                 color: tuple, width: int = 2, dash: int = 8, gap: int = 5) -> None:
    """Draw a horizontal or vertical dashed line (simplified: horizontal only)."""
    if y1 == y2:  # horizontal
        x = x1
        while x < x2:
            draw.line((x, y1, min(x + dash, x2), y1), fill=color, width=width)
            x += dash + gap
    else:  # vertical
        y = y1
        while y < y2:
            draw.line((x1, y, x1, min(y + dash, y2)), fill=color, width=width)
            y += dash + gap


# ---------------------------------------------------------------------------
# Per-boss draw functions
# ---------------------------------------------------------------------------

def _draw_hydross(W: int, H: int) -> "Image.Image":
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    f_lg = _font(12); f_md = _font(11); f_sm = _font(10); f_xs = _font(9)

    mid = H // 2
    # Frost zone
    _zone_rect(d, 30, 25, W-30, mid-15, FROST, FROST_B, "FROST FORM ZONE", f_sm)
    # Pillars
    d.rectangle((70, 55, 85, mid-30), fill=(74, 112, 144))
    d.rectangle((W-85, 55, W-70, mid-30), fill=(74, 112, 144))
    # Hydross
    bx = W // 2
    _boss_circle(d, bx, 130, 24, (90, 144, 192), FROST_T, "HYDROSS", f_md)
    # Frost MT
    _dot(d, bx, 175, 10, BLUE, FROST_T, "[Frost MT]", "{skull}", f_sm, f_xs)
    # Spread reminder
    d.text((50, 80), "← Raid spreads 8 yd →", fill=MUTED, font=f_xs)

    # Flag boundary
    _dashed_line(d, 30, mid-5, W-30, mid-5, GOLD, width=3)
    d.text((60, mid-16), "▶ FLAG BOUNDARY ◀", fill=GOLD, font=f_xs)

    # Nature zone
    _zone_rect(d, 30, mid+10, W-30, H-20, NATURE, NATURE_B, "POISON FORM ZONE", f_sm)
    # Nature MT
    _dot(d, bx, mid+75, 10, BLUE, NATURE_T, "[Nature MT]", "{cross}", f_sm, f_xs)
    # Add OT
    _dot(d, 90, mid+75, 10, RED, RED, "[Add OT]", "{triangle}", f_sm, f_xs)

    # Title
    d.text((30, 8), "Hydross the Unstable — Position Map", fill=GOLD, font=f_lg)
    return img


def _draw_lurker(W: int, H: int) -> "Image.Image":
    img = Image.new("RGB", (W, H), (10, 24, 40))
    d = ImageDraw.Draw(img)
    f_lg = _font(12); f_md = _font(11); f_sm = _font(10); f_xs = _font(9)

    cx, cy, pr = W//2, H//2, min(W, H)//2 - 40
    # Water background (already dark blue)
    # Platform
    d.ellipse((cx-pr, cy-pr, cx+pr, cy+pr), fill=(58, 80, 96), outline=(122, 150, 173), width=2)
    # 4 pillars at corners
    for px, py in [(cx-90, cy-90), (cx+90, cy-90), (cx-90, cy+90), (cx+90, cy+90)]:
        d.ellipse((px-14, py-14, px+14, py+14), fill=(90, 106, 120), outline=(170, 184, 197), width=1)

    # Lurker center
    _boss_circle(d, cx, cy, 26, (90, 138, 106), (159, 212, 175), "LURK", f_md)
    # MT behind pillar (left pillar)
    _dot(d, cx-90, cy-2, 10, BLUE, BLUE, "[MT]", "{skull}", f_sm, f_xs)
    # Naga OT (outer)
    _dot(d, cx, cy+pr-25, 10, RED, RED, "[Naga OT]", "{cross}", f_sm, f_xs)

    # Spout arrow hint (rotating)
    d.line((cx, cy, cx+pr-15, cy-60), fill=GOLD, width=2)
    d.text((cx+pr-60, cy-75), "SPOUT →", fill=GOLD, font=f_xs)

    # Jump-in note
    d.text((10, H-25), "Spout: EVERYONE jumps in water  |  Ranged stack around platform edge", fill=FROST_T, font=f_xs)
    d.text((30, 8), "The Lurker Below — Position Map", fill=GOLD, font=f_lg)
    return img


def _draw_morogrim(W: int, H: int) -> "Image.Image":
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    f_lg = _font(12); f_md = _font(11); f_sm = _font(10); f_xs = _font(9)

    # Room border
    d.rectangle((25, 25, W-25, H-55), fill=PANEL, outline=(68, 85, 85), width=1)
    # Entrance
    d.rectangle((W//2-50, H-75, W//2+50, H-30), fill=(42, 58, 72), outline=(85, 102, 102))
    d.text((W//2-28, H-60), "ENTRANCE", fill=MUTED, font=f_xs)
    d.text((W//2-38, H-50), "(move here 25%)", fill=GOLD, font=f_xs)

    # Morogrim center
    bx, by = W//2, H//2 - 30
    _boss_circle(d, bx, by, 26, (64, 106, 128), (136, 187, 204), "MORO", f_md)
    _dot(d, bx, by + 55, 10, BLUE, BLUE, "[MT]", "{skull}", f_sm, f_xs)

    # Murloc spawn corners (green boxes)
    corners = [(55, 50), (W-55, 50), (55, H-120), (W-55, H-120)]
    for mx, my in corners:
        d.rectangle((mx-22, my-22, mx+22, my+22), fill=(58, 80, 64), outline=(127, 175, 138), width=2)
        _text_center(d, mx, my, "M", _font(16), NATURE_T)

    d.text((30, H//2 - 15), "← Murloc spawn corners\n   (after each Earthquake)", fill=NATURE_T, font=f_xs)

    # Murloc OT position
    _dot(d, 120, by + 20, 10, RED, RED, "[Murloc OT]", "{cross}", f_sm, f_xs)

    d.text((30, 8), "Morogrim Tidewalker — Position Map", fill=GOLD, font=f_lg)
    return img


def _draw_karathress(W: int, H: int) -> "Image.Image":
    img = Image.new("RGB", (W, H), (19, 32, 42))
    d = ImageDraw.Draw(img)
    f_lg = _font(12); f_md = _font(11); f_sm = _font(10); f_xs = _font(9)

    d.rectangle((20, 20, W-20, H-20), fill=(20, 32, 43), outline=(68, 68, 85))

    bx, by = W//2, H//2
    # Karathress center
    _boss_circle(d, bx, by, 26, (106, 58, 58), (204, 136, 136), "KARA", f_md)
    d.text((bx-28, by+30), "[MT]  {skull}", fill=(204, 136, 136), font=f_xs)
    d.text((bx-22, by+42), "kill 4th", fill=MUTED, font=f_xs)

    # Sharkkis (top-left)
    _boss_circle(d, 115, 100, 22, (58, 90, 64), (136, 204, 136), "SHRK", f_md)
    d.text((55, 128), "[Tank B]  {cross}", fill=(136, 204, 136), font=f_xs)
    d.text((55, 140), "kill 2nd", fill=MUTED, font=f_xs)

    # Tidalvess (top-right)
    _boss_circle(d, W-115, 100, 22, (58, 74, 106), (136, 170, 204), "TIDL", f_md)
    d.text((W-165, 128), "{triangle} [Tank C]", fill=(136, 170, 204), font=f_xs)
    d.text((W-152, 140), "kill 1st!", fill=GOLD, font=f_xs)

    # Caribdis (bottom-right, far corner)
    _boss_circle(d, W-90, H-90, 22, (90, 58, 106), (204, 136, 204), "CARI", f_md)
    d.text((W-185, H-65), "{moon} [Tank D]", fill=(204, 136, 204), font=f_xs)
    d.text((W-170, H-53), "kill 3rd", fill=MUTED, font=f_xs)
    d.text((W-185, H-41), "INTERRUPT!", fill=RED, font=f_xs)

    # Kill order banner
    d.rectangle((25, H-40, W-25, H-12), fill=DARK, outline=GOLD)
    _text_center(d, W//2, H-26, "KILL: Tidalvess → Sharkkis → Caribdis → Karathress", f_sm, GOLD)

    d.text((30, 8), "Fathom-Lord Karathress — Position Map", fill=GOLD, font=f_lg)
    return img


def _draw_leotheras(W: int, H: int) -> "Image.Image":
    img = Image.new("RGB", (W, H), (26, 21, 48))
    d = ImageDraw.Draw(img)
    f_lg = _font(12); f_md = _font(11); f_sm = _font(10); f_xs = _font(9)

    cx, cy = W//2, H//2
    # Spread ring
    d.ellipse((cx-140, cy-140, cx+140, cy+140), fill=None, outline=(169, 135, 217), width=1)
    d.text((cx-75, cy+145), "SPREAD 30 yd (Inner Demons)", fill=PURPLE, font=f_xs)

    # Boss
    _boss_circle(d, cx, cy, 26, (90, 58, 122), (169, 135, 217), "LEO", f_md)
    # Humanoid tank (above)
    _dot(d, cx, cy - 65, 10, BLUE, BLUE, "[Humanoid MT]", "{skull}", f_sm, f_xs)
    # Demon tank (below)
    _dot(d, cx, cy + 65, 10, RED, RED, "[Demon FR Tank]", "{cross}", f_sm, f_xs)
    d.text((cx-40, cy+90), "Fire Res gear!", fill=RED, font=f_xs)

    # Spread position dots
    import math
    for i in range(8):
        angle = math.radians(i * 45 + 22)
        sx = int(cx + 120 * math.cos(angle))
        sy = int(cy + 120 * math.sin(angle))
        d.ellipse((sx-5, sy-5, sx+5, sy+5), fill=MUTED)

    # Phase banner
    d.rectangle((20, H-42, W-20, H-12), fill=DARK, outline=GOLD)
    _text_center(d, W//2, H-27, "15%: Both forms active — burn HUMANOID form down", f_sm, GOLD)

    d.text((30, 8), "Leotheras the Blind — Position Map", fill=GOLD, font=f_lg)
    return img


def _draw_vashj(W: int, H: int) -> "Image.Image":
    img = Image.new("RGB", (W, H), (10, 8, 32))
    d = ImageDraw.Draw(img)
    f_lg = _font(12); f_md = _font(11); f_sm = _font(10); f_xs = _font(9)

    cx, cy = W//2, H//2
    pr = min(W, H)//2 - 35
    # Main platform
    d.ellipse((cx-pr, cy-pr, cx+pr, cy+pr), fill=(42, 53, 80), outline=(102, 136, 170), width=2)
    # Inner ring
    d.ellipse((cx-pr+55, cy-pr+55, cx+pr-55, cy+pr-55), fill=None, outline=(102, 136, 170), width=1)

    # Vashj center
    _boss_circle(d, cx, cy, 22, (122, 74, 138), (204, 153, 221), "VASHJ", f_md)
    d.text((cx-25, cy+25), "[MT] {skull}", fill=(204, 153, 221), font=f_xs)

    # 4 Generators at cardinal diagonals
    gens = {
        "G1 NW": (-pr+55, -pr+55, "[NW Catcher]", ORANGE),
        "G2 NE": ( pr-55, -pr+55, "[NE Catcher]", ORANGE),
        "G3 SE": ( pr-55,  pr-55, "[SE Catcher]", ORANGE),
        "G4 SW": (-pr+55,  pr-55, "[SW Catcher]", ORANGE),
    }
    gen_positions = []
    for label, (dx, dy, catcher, col) in gens.items():
        gx, gy = cx + dx, cy + dy
        gen_positions.append((gx, gy))
        d.rectangle((gx-16, gy-16, gx+16, gy+16), fill=(170, 119, 51), outline=(255, 204, 102), width=2)
        _text_center(d, gx, gy, label[:2], f_md, WHITE)
        # Catcher dot at outer edge
        factor = 1.45
        catx = int(cx + dx * factor)
        caty = int(cy + dy * factor)
        catx = max(15, min(W-15, catx))
        caty = max(15, min(H-45, caty))
        d.ellipse((catx-8, caty-8, catx+8, caty+8), fill=GREEN, outline=GREEN)
        _text_center(d, catx, caty + 14, catcher, f_xs, GREEN)
        # Line from catcher to generator
        d.line((catx, caty, gx, gy), fill=(136, 204, 136), width=1)

    # Tainted elemental label
    d.text((10, H-35), "Tainted Elementals: ranged kills fast (15s) → throw core to catcher", fill=PURPLE, font=f_xs)
    d.text((10, H-22), "Strider Kiter: runs WIDE outer circle  |  Elites tank: center stairs", fill=MUTED, font=f_xs)

    d.text((30, 8), "Lady Vashj — P2 Generator Map", fill=GOLD, font=f_lg)
    return img


def _draw_alar(W: int, H: int) -> "Image.Image":
    img = Image.new("RGB", (W, H), (16, 10, 8))
    d = ImageDraw.Draw(img)
    f_lg = _font(12); f_md = _font(11); f_sm = _font(10); f_xs = _font(9)

    cx, cy = W//2, H//2
    # 4 platforms in a square
    plat_r = 50
    positions = {
        "1": (cx - 155, cy - 100),
        "2": (cx + 155, cy - 100),
        "3": (cx + 155, cy + 100),
        "4": (cx - 155, cy + 100),
    }
    colors = {
        "1": ((58, 40, 24), (204, 136, 68), "START"),
        "2": ((58, 40, 24), (204, 136, 68), ""),
        "3": ((58, 40, 24), (204, 136, 68), ""),
        "4": ((58, 40, 24), (204, 136, 68), ""),
    }
    for num, (px, py) in positions.items():
        fill, border, note = colors[num]
        d.ellipse((px-plat_r, py-plat_r, px+plat_r, py+plat_r), fill=fill, outline=border, width=2)
        _text_center(d, px, py-12, num, _font(20), (255, 204, 136))
        if note:
            _text_center(d, px, py+14, note, f_xs, GOLD)

    # Rotation arrows (1→2→3→4→1)
    seqs = [("1","2"), ("2","3"), ("3","4"), ("4","1")]
    for a, b in seqs:
        ax, ay = positions[a]
        bx, by = positions[b]
        mx, my = (ax+bx)//2, (ay+by)//2
        d.line((ax, ay, bx, by), fill=GOLD, width=1)
        d.ellipse((mx-4, my-4, mx+4, my+4), fill=GOLD)

    # Ground center
    _dot(d, cx, cy, 10, RED, RED, "[Ground Tank]", "{triangle}", f_sm, f_xs)
    d.text((cx-65, cy+30), "Ember adds", fill=MUTED, font=f_xs)

    # Tank positions note
    d.text((cx-75, cy-75), "Tank A {skull}", fill=BLUE, font=f_xs)
    d.text((cx+15, cy-75), "Tank B {cross}", fill=BLUE, font=f_xs)

    d.text((10, H-35), "P1: RANGED ONLY can hit Al'ar during platform phase", fill=FROST_T, font=f_xs)
    d.text((10, H-22), "P2: Al'ar lands center — Bloodlust on pull", fill=GOLD, font=f_xs)
    d.text((30, 8), "Al'ar — Platform Rotation Map", fill=GOLD, font=f_lg)
    return img


def _draw_solarian(W: int, H: int) -> "Image.Image":
    img = Image.new("RGB", (W, H), (15, 24, 40))
    d = ImageDraw.Draw(img)
    f_lg = _font(12); f_md = _font(11); f_sm = _font(10); f_xs = _font(9)

    cx, cy = W//2, H//2
    pr = min(W, H)//2 - 35
    # Circular room
    d.ellipse((cx-pr, cy-pr, cx+pr, cy+pr), fill=(26, 37, 64), outline=(85, 119, 170), width=2)

    # Boss center
    _boss_circle(d, cx, cy, 22, (170, 119, 51), (255, 204, 102), "SOLA", f_md)
    # MT below boss
    _dot(d, cx, cy + 55, 10, BLUE, BLUE, "[MT]", "{skull}", f_sm, f_xs)

    # 3 portals
    portals = [
        (cx, cy - pr + 20, "P1", "Portal N"),
        (cx - 125, cy + 100, "P2", "Portal SW"),
        (cx + 125, cy + 100, "P3", "Portal SE"),
    ]
    for px, py, label, desc in portals:
        d.ellipse((px-18, py-18, px+18, py+18), fill=(90, 58, 122), outline=(204, 153, 221), width=2)
        _text_center(d, px, py, label, f_md, WHITE)
        _text_center(d, px, py + 24, desc, f_xs, PURPLE)

    # Wrath note
    d.line((cx, cy, 30, cy - 30), fill=RED, width=1)
    d.text((8, cy - 45), "Wrath target:", fill=RED, font=f_xs)
    d.text((8, cy - 33), "RUN to wall →", fill=RED, font=f_xs)

    # Ranged stack
    for rx, ry in [(cx-20, cy+70), (cx+20, cy+70), (cx-20, cy+90), (cx+20, cy+90)]:
        d.ellipse((rx-4, ry-4, rx+4, ry+4), fill=PURPLE)
    d.text((cx-60, cy+102), "Ranged stack behind MT", fill=PURPLE, font=f_xs)

    d.text((10, H-22), "Add phase: AoE priests fast — interrupt their heals!", fill=NATURE_T, font=f_xs)
    d.text((30, 8), "High Astromancer Solarian — Position Map", fill=GOLD, font=f_lg)
    return img


def _draw_kaelthas(W: int, H: int) -> "Image.Image":
    img = Image.new("RGB", (W, H), (10, 8, 21))
    d = ImageDraw.Draw(img)
    f_lg = _font(12); f_md = _font(11); f_sm = _font(10); f_xs = _font(9)

    # Room border
    d.rectangle((20, 20, W-20, H-20), fill=(26, 21, 37), outline=(119, 85, 170), width=2)

    # Kael platform (top)
    d.rectangle((W//2-80, 28, W//2+80, 85), fill=(58, 37, 72), outline=(170, 136, 204), width=2)
    _text_center(d, W//2, 48, "KAEL'THAS", f_md, (255, 204, 136))
    _text_center(d, W//2, 68, "P4+ joins here", f_xs, PURPLE)

    # 4 advisors
    advisors = [
        (115, 175, "THAL", (58, 90, 64), (136, 204, 136), "[Kiter]", "{skull}", "Kite around room!"),
        (W-115, 175, "SANG", (90, 58, 58), (204, 136, 136), "[Tank B]", "{cross}", "Fear Ward tank"),
        (115, H-115, "CAPN", (170, 96, 51), (255, 204, 102), "[Warlock]", "{triangle}", "Lock-tank (Sacrifice)"),
        (W-115, H-115, "TELO", (58, 74, 106), (136, 170, 204), "[Tank D]", "{moon}", "Watch bombs!"),
    ]
    kill_nums = ["1st kill", "2nd kill", "3rd kill", "4th kill"]
    for i, (ax, ay, label, fill, border, role, marker, note) in enumerate(advisors):
        d.ellipse((ax-28, ay-28, ax+28, ay+28), fill=fill, outline=border, width=2)
        _text_center(d, ax, ay, label, f_sm, WHITE)
        _text_center(d, ax, ay+35, role, f_xs, border)
        _text_center(d, ax, ay+47, f"{marker} {kill_nums[i]}", f_xs, GOLD)
        _text_center(d, ax, ay+59, note, f_xs, MUTED)

    # Kill order at bottom
    d.rectangle((25, H-42, W-25, H-12), fill=DARK, outline=GOLD)
    _text_center(d, W//2, H-27, "P1 Kill: Thaladred → Sanguinar → Capernian → Telonicus", f_sm, GOLD)

    d.text((30, 8), "Kael'thas Sunstrider — P1 Advisor Map", fill=GOLD, font=f_lg)
    return img


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_DRAW_FNS = {
    "hydross":     _draw_hydross,
    "lurker":      _draw_lurker,
    "morogrim":    _draw_morogrim,
    "karathress":  _draw_karathress,
    "leotheras":   _draw_leotheras,
    "vashj":       _draw_vashj,
    "alar":        _draw_alar,
    "solarian":    _draw_solarian,
    "kaelthas":    _draw_kaelthas,
}

_SIZES = {
    "vashj":   (620, 620),
    "kaelthas":(620, 580),
    "default": (620, 500),
}


def generate_diagram(boss_key: str) -> Optional[bytes]:
    """Return PNG bytes for the boss position diagram, or None if unavailable."""
    if not _PIL_AVAILABLE:
        return None
    fn = _DRAW_FNS.get(boss_key)
    if fn is None:
        return None
    W, H = _SIZES.get(boss_key, _SIZES["default"])
    try:
        img = fn(W, H)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception:
        return None
