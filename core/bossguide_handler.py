"""
bossguide_handler.py — pipeline entry point for /bossguide.

Flow:
  1. Resolve boss name to canonical key.
  2. If image bytes provided (roster screenshot): call Claude Vision to extract
     names/roles, then call Claude to generate tailored assignments.
  3. If no image: call Claude to generate template-style assignments with
     [Tank1], [Healer1] placeholders.
  4. Optionally generate a position diagram PNG via bossguide_diagram.
  5. Return (assignment_text: str, diagram_png: bytes | None).

Returns strings and bytes — never posts to Discord directly.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Optional, Tuple

import config
from core.bossguide_data import BOSS_DATA, resolve_boss, BossEntry

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt for Claude assignment generation
# ---------------------------------------------------------------------------

ASSIGNMENT_SYSTEM = """\
You are BrnzyBot, a World of Warcraft TBC raid assignment generator for an experienced raid leader.

Your output has TWO parts separated by a line containing only "---".

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PART 1 — ASSIGNMENTS (before the ---)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Each line will be sent as a /ra (raid alert) command in WoW. Rules:
1. Open with:  ━━━ {skull} <Boss Name> {skull} ━━━
2. Use ALL-CAPS section headers: TANKS, HEALS, MD CHAIN, INTERRUPTS, SPECIALTY
4. Each TANKS line: <marker> <Role Label>: <Name or [Placeholder]>
5. Each HEALS line: <Role Label>: <Name1>  <Name2>
6. NO explanations, NO dashes, NO "— tanks between pillars" text. Names/roles only.
7. Keep every line under 80 characters (WoW chat limit).
8. Blank lines between sections are fine.
9. Omit sections not relevant to this fight.

WoW markers (use only those specified in boss context):
   {skull} {cross} {triangle} {moon} {star} {square} {circle} {diamond}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PART 2 — NOTES (after the ---)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Plain text for the raid leader's reference. Include:
- MELEE: 1–2 sentences on positioning, movement, add/phase priority.
- RULES: bullet points starting with •, 4–6 lines. Specific and action-oriented.
No /ra prefix here. No markdown, no bold, no asterisks.

SPELL NAMES: Never reference specific spell names.
Use generic terms: "AoE adds", "fire resist set", "AoE down fast", etc.

If using roster data from an image: assign specific player names. Fill ALL named roles.
If no roster (template mode): use descriptive placeholders like [Frost MT], [Healer 1], [MD Hunter].
"""

ROSTER_PARSE_SYSTEM = """\
You are analyzing a World of Warcraft screenshot to extract raid roster information.

Extract a JSON object with this structure:
{
  "tanks": ["Name1", "Name2", ...],
  "healers": ["Name1", "Name2", ...],
  "dps": ["Name1", "Name2", ...],
  "hunters": ["Name1", ...],
  "classes": {"Name1": "warrior", "Name2": "paladin", ...}
}

Guidelines:
- Identify player names from the raid frame, raid composition window, or any visible player list.
- Classify by role icon (shield=tank, cross=healer, sword=dps) or by class color if visible.
- Warrior class color: tan/brown. Paladin: pink/light purple. Druid: orange. Shaman: blue.
  Hunter: olive/lime green. Rogue: yellow. Mage: light blue. Warlock: purple. Priest: white.
- If class is uncertain, omit from "classes" rather than guess wrongly.
- Hunters should appear in BOTH "dps" and "hunters" lists.
- Return ONLY the JSON object, no explanation.
"""


# ---------------------------------------------------------------------------
# LiteLLM call (reused from gear_reasoning pattern)
# ---------------------------------------------------------------------------

def _call_llm(messages: list, system: str, temperature: float = 0.2,
              timeout: int = 60, image_b64: str = None,
              image_mime: str = "image/png") -> str:
    """
    Call Claude via LiteLLM proxy.
    If image_b64 is provided, the last user message gets the image prepended
    using the OpenAI-compatible vision format.
    """
    from core import llm
    full_messages = [{"role": "system", "content": system}]

    for msg in messages:
        if msg.get("role") == "user" and image_b64 and not full_messages[1:]:
            full_messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{image_mime};base64,{image_b64}"},
                    },
                    {"type": "text", "text": msg["content"]},
                ],
            })
        else:
            full_messages.append(msg)

    return llm.chat(config.MODEL_ESCALATION, full_messages,
                    temperature=temperature, max_tokens=1600, timeout=timeout)


# ---------------------------------------------------------------------------
# Roster image parsing
# ---------------------------------------------------------------------------

def _parse_roster_image(image_bytes: bytes) -> dict:
    """Call Claude Vision on a roster screenshot. Returns a roster dict."""
    b64 = base64.b64encode(image_bytes).decode()
    # Detect image type from magic bytes
    mime = "image/png"
    if image_bytes[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    elif image_bytes[:4] == b"GIF8":
        mime = "image/gif"
    elif image_bytes[:4] == b"RIFF":
        mime = "image/webp"

    try:
        response = _call_llm(
            messages=[{"role": "user", "content": "Extract raid roster information from this screenshot."}],
            system=ROSTER_PARSE_SYSTEM,
            image_b64=b64,
            image_mime=mime,
            temperature=0.1,
            timeout=45,
        )
        # Strip markdown code fences if present
        text = response.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception as e:
        log.warning("Roster image parse failed: %s", e)
        return {}


# ---------------------------------------------------------------------------
# Assignment generation
# ---------------------------------------------------------------------------

def _build_assignment_prompt(entry: BossEntry, roster: dict) -> str:
    """Build the user-turn prompt for Claude assignment generation."""
    lines = [
        f"Generate raid assignments for: {entry.full_name}",
        f"Raid: {entry.raid} | Boss {entry.boss_num}",
        "",
        "BOSS CONTEXT:",
        entry.context,
    ]

    if roster:
        lines += [
            "",
            "ROSTER (from screenshot):",
            f"  Tanks:   {', '.join(roster.get('tanks',   [])) or 'none identified'}",
            f"  Healers: {', '.join(roster.get('healers', [])) or 'none identified'}",
            f"  DPS:     {', '.join(roster.get('dps',     [])) or 'none identified'}",
            f"  Hunters: {', '.join(roster.get('hunters', [])) or 'none identified'}",
        ]
        if roster.get("classes"):
            cls_lines = ", ".join(f"{n}={c}" for n, c in roster["classes"].items())
            lines.append(f"  Classes: {cls_lines}")
        lines += [
            "",
            "Assign specific player names from the roster to each role.",
            "Use class info to pick appropriate players (warriors/paladins for tanks, etc.).",
        ]
    else:
        lines += [
            "",
            "No roster provided — generate template assignments using descriptive placeholders:",
            "  Tanks: [Frost MT], [Nature MT], [Add OT] etc.",
            "  Healers: [Healer 1], [Healer 2] etc.",
            "  Hunters: [MD Hunter 1], [MD Hunter 2]",
            "  Interrupts: [Int 1], [Int 2]",
            "  Specialty: [Kiter], [Cube Catcher NW] etc.",
        ]

    return "\n".join(lines)


def _generate_assignments(entry: BossEntry, roster: dict) -> str:
    """Call Claude to produce formatted WoW assignments."""
    if not config.ENABLE_LLM:
        return _fallback_template(entry)
    prompt = _build_assignment_prompt(entry, roster)
    try:
        raw = _call_llm(
            messages=[{"role": "user", "content": prompt}],
            system=ASSIGNMENT_SYSTEM,
            temperature=0.2,
            timeout=60,
        )
        return _format_ra_output(raw)
    except Exception as e:
        log.error("Assignment generation failed for %s: %s", entry.full_name, e)
        return _fallback_template(entry)


def _format_ra_output(raw: str) -> str:
    """
    Split LLM output on '---' separator, prefix assignment lines with /ra,
    and append the notes block as plain text.
    Returns the final Discord-ready string.
    """
    # Split on the separator line (allow surrounding whitespace/newlines)
    parts = raw.split("\n---\n", 1)
    if len(parts) == 1:
        # No separator found — try looser split
        parts = raw.split("---", 1)

    assignments_raw = parts[0].strip()
    notes_raw = parts[1].strip() if len(parts) > 1 else ""

    # Prefix every non-empty assignment line with /ra
    ra_lines = []
    for line in assignments_raw.splitlines():
        if line.strip():
            ra_lines.append(f"/ra {line}")
        # skip blank lines — no empty /ra commands

    ra_block = "\n".join(ra_lines)

    if notes_raw:
        return ra_block + "\n\n" + notes_raw
    return ra_block


def _fallback_template(entry: BossEntry) -> str:
    """Bare-minimum fallback if Claude call fails entirely."""
    _markers = ["{skull}", "{cross}", "{triangle}", "{moon}", "{star}"]
    n = entry.roles.get("tanks", 1)
    tank_lines = "\n".join(
        f"  {_markers[i] if i < len(_markers) else ''} [Tank {i+1}]"
        for i in range(n)
    )
    return (
        f"━━━ {{skull}} {entry.full_name} {{skull}} ━━━\n"
        f"{entry.raid} · Boss {entry.boss_num}\n\n"
        f"TANKS\n{tank_lines}\n\n"
        f"HEALS\n  [Healer 1]  [Healer 2]  [Healer 3]\n\n"
        f"_Template assignments — fill in the placeholders. "
        f"AI roster auto-assignment is currently off._"
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def handle_bossguide(boss_name: str,
                     image_bytes: Optional[bytes] = None
                     ) -> Tuple[str, Optional[bytes]]:
    """
    Main entry point for /bossguide command.

    Args:
        boss_name:   Raw user input (e.g. "hydross", "lady vashj", "kael").
        image_bytes: PNG/JPEG bytes of a raid roster screenshot, or None.

    Returns:
        (assignment_text, diagram_png_bytes)
        diagram_png_bytes is None for non-positional fights or if Pillow unavailable.
    """
    boss_key = resolve_boss(boss_name)
    if boss_key is None:
        available = ", ".join(k for k in BOSS_DATA)
        return (
            f"Unknown boss: **{boss_name}**\n"
            f"Available: {available}",
            None,
        )

    entry = BOSS_DATA[boss_key]
    log.info("bossguide: %s (image=%s)", boss_key, image_bytes is not None)

    # Parse roster image if provided (requires Claude Vision — LLM-only).
    roster: dict = {}
    if image_bytes and config.ENABLE_LLM:
        roster = _parse_roster_image(image_bytes)
        log.info("bossguide roster parse: tanks=%s healers=%s dps=%s",
                 roster.get("tanks"), roster.get("healers"), roster.get("dps"))

    # Generate text assignments
    text = _generate_assignments(entry, roster)

    # Generate position diagram
    diagram: Optional[bytes] = None
    if entry.has_diagram:
        try:
            from core.bossguide_diagram import generate_diagram
            diagram = generate_diagram(boss_key)
        except Exception as e:
            log.warning("Diagram generation failed for %s: %s", boss_key, e)

    return text, diagram
