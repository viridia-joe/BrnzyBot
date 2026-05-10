"""
BrnzyBot SimExport Cog — /simexport slash command.

Fetches a character's latest WCL gear snapshot and produces a
WowSims-compatible JSON file the user can import directly at
https://wowsims.github.io/tbc/

Usage:
    /simexport <character> [spec] [phase]
"""

from __future__ import annotations

import asyncio
import io
import json
import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.gear_handler import handle_gear_question   # reuse _resolve_character path
from cogs.gear import _resolve_character, _try_auto_register
from db.server_config import get_character, log_usage, check_rate_limit

log = logging.getLogger(__name__)


class SimExportCog(commands.Cog, name="SimExport"):
    """WowSims JSON export for character gear snapshots."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="simexport",
        description="Export your current gear as a WowSims import file (.json).",
    )
    @app_commands.describe(
        character="Character name (must be registered with /addchar)",
        spec="Spec override (e.g. elemental, destro, shadow). Uses registered spec if omitted.",
        phase="Phase to target (1–5). Defaults to guild's current phase.",
    )
    async def slash_simexport(
        self,
        interaction: discord.Interaction,
        character: str,
        spec: str | None = None,
        phase: int | None = None,
    ) -> None:
        guild_id = str(interaction.guild_id)

        allowed, _ = check_rate_limit(guild_id)
        if not allowed:
            await interaction.response.send_message(
                "This server has hit the free plan daily limit (20 commands). "
                "Upgrade to Pro for unlimited usage — use `/subscribe`.",
                ephemeral=True,
            )
            return

        if phase is not None and not (1 <= phase <= 5):
            await interaction.response.send_message(
                "Phase must be between 1 and 5.", ephemeral=True
            )
            return

        display, reg_spec, realm, region = _resolve_character(character, guild_id)
        auto_note = None
        if display is None:
            auto_result = await _try_auto_register(
                character, guild_id, added_by=str(interaction.user.id)
            )
            if auto_result is None:
                await interaction.response.send_message(reg_spec, ephemeral=True)
                return
            display, reg_spec, realm, region, auto_note = auto_result

        resolved_spec = spec or reg_spec
        await interaction.response.defer(thinking=True)
        log_usage(guild_id, str(interaction.user.id), "simexport")

        loop = asyncio.get_running_loop()
        try:
            export_dict = await loop.run_in_executor(
                None,
                lambda: _build_export(display, resolved_spec, realm, region or "us",
                                      guild_id, phase),
            )
        except Exception as exc:
            log.exception("simexport failed for %s", display)
            await interaction.followup.send(
                f"Export failed for **{display}**: {exc}", ephemeral=True
            )
            return

        if export_dict is None:
            await interaction.followup.send(
                f"No gear data found for **{display}** — WCL may be unreachable "
                "and no cached snapshot exists. Try `/gearprio` first to populate the cache.",
                ephemeral=True,
            )
            return

        export_dict, meta = export_dict  # _build_export returns (dict, meta)
        phase        = meta["phase"]
        has_enchants = meta["has_enchants"]
        has_gems     = meta["has_gems"]
        from_cache   = meta["from_cache"]

        json_bytes = json.dumps(export_dict, indent=2).encode("utf-8")
        filename = f"{display.lower()}_{resolved_spec}_p{phase}_sim.json"
        file = discord.File(fp=io.BytesIO(json_bytes), filename=filename)

        lines = [f"**WowSims export — {display} ({resolved_spec})**"]
        lines.append("Import at <https://wowsims.github.io/tbc/>  →  Settings → Import")
        lines.append("")
        lines.append("**What's included:** item IDs, spec defaults, EP weights, buffs/debuffs")
        lines.append("**What to fill in after import:** talent string, any adjusted consumables")
        if from_cache:
            lines.append("⚠ Gear from cache — enchants and gems may be missing. "
                         "Run `/gearprio` to refresh from WCL, then re-export.")
        elif not has_enchants:
            lines.append("⚠ Enchant IDs not found in this WCL log — add manually in wowsims.")
        elif not has_gems:
            lines.append("⚠ Gem IDs not found in this WCL log — add manually in wowsims.")
        if auto_note:
            lines.append(auto_note)

        await interaction.followup.send("\n".join(lines), file=file)


def _build_export(character: str, spec: str, realm: str, region: str,
                  guild_id: str, phase_override: int | None) -> dict | None:
    """Fetch gear snapshot and build the wowsims export dict."""
    import sqlite3, os
    import config
    from core.gear_cache import get_gear
    from core.simexport import build_simexport
    from core.classifier import SPEC_ALIASES

    spec = SPEC_ALIASES.get(spec.lower(), spec.lower())

    item_db = sqlite3.connect(config.ITEM_DB_PATH) if os.path.exists(config.ITEM_DB_PATH) else None
    try:
        snapshot = get_gear(character, realm, spec, region=region, item_db_conn=item_db)
    finally:
        if item_db:
            item_db.close()

    if snapshot is None:
        return None

    return build_simexport(snapshot, spec, guild_id, phase_override=phase_override)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SimExportCog(bot))
