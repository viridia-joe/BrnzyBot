"""
Raid Audit Matrix — stage 3: render the graded matrix to compact Discord text.

Layout (per docs/RAID_AUDIT_MATRIX.md):
  - Gems & Enchants: one roster-wide summary table (these don't change per pull).
  - Food / Weapon Oil / Potion: ✅/⚠️/❌ grids, players × boss columns.
  - Elixirs / Flasks: shows the named consumable per cell (the detailed row).
  - Bosses chunked into wings of ≤6 columns so tables stay readable.

Tables are rendered inside ``` code blocks for monospace alignment.
"""

from __future__ import annotations

import time

from core.audit.matrix import chunk_fights, RaidMatrix
from core.audit.matrix_grade import grade_cell, OK, SUB, MISSING, NA
from core.audit.report import _socket_info  # reuse the socket/meta scan
from core.audit.profiles import get_profile


def _abbrev(name: str, width: int = 8) -> str:
    """Short boss-name column header."""
    n = name.split(" the ")[0].split(",")[0].strip()
    return (n[:width]).ljust(width)


def _zone_of(matrix: RaidMatrix) -> str:
    """Best-effort zone name from the fights (matrix.zone is often empty)."""
    if matrix.zone:
        return matrix.zone
    names = " ".join(f["name"].lower() for f in matrix.fights)
    for zone, keys in (
        ("Serpentshrine Cavern", ("hydross", "vashj", "lurker", "morogrim")),
        ("Tempest Keep", ("al'ar", "void reaver", "kael", "solarian")),
        ("Karazhan", ("attumen", "moroes", "curator", "nightbane", "malchezaar")),
        ("Gruul's Lair", ("gruul", "maulgar")),
        ("Magtheridon's Lair", ("magtheridon",)),
    ):
        if any(k in names for k in keys):
            return zone
    return ""


def _grid_table(matrix: RaidMatrix, fight_idxs: list[int], slot_key: str) -> str:
    """A ✅/⚠️/❌ grid for one consumable slot over the given fight columns."""
    fights = [matrix.fights[i] for i in fight_idxs]
    name_w = max((len(p["name"]) for p in matrix.players), default=8)
    name_w = min(max(name_w, 6), 14)

    header = " " * name_w + "  " + " ".join(_abbrev(f["name"]) for f in fights)
    rows = [header]
    for p in matrix.players:
        cells = matrix.cells.get(p["name"], {})
        marks = []
        for f in fights:
            c = cells.get(f["id"])
            if not c or not c.present:
                marks.append(NA.center(8))
                continue
            graded = grade_cell(c, f["name"])
            mark = graded.get(slot_key, (NA, ""))[0]
            marks.append(mark.center(8))
        # only show players who were present in at least one of these fights
        if any(m.strip() != NA for m in marks):
            rows.append(p["name"].ljust(name_w) + "  " + " ".join(marks))
    return "```\n" + "\n".join(rows) + "\n```"


def _elixir_table(matrix: RaidMatrix, fight_idxs: list[int]) -> str:
    """Per-fight named flask/elixir with its ✅/⚠️/❌ mark (the detailed view)."""
    fights = [matrix.fights[i] for i in fight_idxs]
    out = []
    for f in fights:
        out.append(f"**{f['name']}**")
        any_row = False
        for p in matrix.players:
            c = matrix.cells.get(p["name"], {}).get(f["id"])
            if not c or not c.present:
                continue
            graded = grade_cell(c, f["name"])
            mark, label = graded.get("elixir", (NA, "—"))
            out.append(f"  {mark} {p['name']}: {label}")
            any_row = True
        if not any_row:
            out.append("  _no data_")
        out.append("")
    return "\n".join(out)


def _gems_enchants_table(matrix: RaidMatrix) -> str:
    """Roster-wide gems + enchants summary (one row per player)."""
    from core.audit.report import check_enchants, check_gems
    name_w = min(max((len(p["name"]) for p in matrix.players), default=8), 16)
    rows = [f"{'':<{name_w}}  Gems   Enchants"]
    for p in matrix.players:
        norm = matrix.gear.get(p["name"])
        profile = get_profile(p["usual_spec"]) if p["usual_spec"] else None
        if not norm or not profile:
            continue
        si = _socket_info(norm.get("gear", []))
        gem_res = check_gems(norm.get("gems", []), profile, si.get("empty_sockets"))
        enc_res = check_enchants(norm.get("gear", []), profile)
        rows.append(f"{p['name']:<{name_w}}  {gem_res.verdict.icon:<5}  {enc_res.verdict.icon} {enc_res.summary}")
    return "```\n" + "\n".join(rows) + "\n```"


def render_matrix(matrix: RaidMatrix) -> str:
    if matrix.warnings and not matrix.fights:
        return "Raid audit: " + "; ".join(matrix.warnings)

    zone = _zone_of(matrix)
    date = ""
    if matrix.start_time:
        date = " · " + time.strftime("%Y-%m-%d", time.gmtime(matrix.start_time / 1000))
    head = (f"# Raid Audit — {zone or 'Report'}{date}\n"
            f"_{len(matrix.players)} raiders × {len(matrix.fights)} boss "
            f"{'kill' if len(matrix.fights) == 1 else 'kills'}_")

    parts = [head, "\n## Gems & Enchants", _gems_enchants_table(matrix)]

    chunks = chunk_fights(zone, [f["name"] for f in matrix.fights])
    for ci, idxs in enumerate(chunks):
        suffix = f" (wing {ci + 1})" if len(chunks) > 1 else ""
        parts.append(f"\n## Food{suffix}")
        parts.append(_grid_table(matrix, idxs, "food"))
        parts.append(f"\n## Weapon Oils / Windfury{suffix}")
        parts.append(_grid_table(matrix, idxs, "weapon_oil"))
        parts.append(f"\n## Elixirs / Flasks{suffix}")
        parts.append(_elixir_table(matrix, idxs))
        parts.append(f"\n## Potion Use{suffix}")
        parts.append(_grid_table(matrix, idxs, "potion"))

    return "\n".join(parts)
