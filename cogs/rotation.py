"""
BrnzyBot Rotation Cog — slash and prefix dispatch for /rotationcheck.

Thin dispatch only: resolve the character, call core.rotation_handler, post
the result. All analysis lives in the handler.

Commands:
    /rotationcheck <character> [spec] [report] [fight]
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from core.rotation_handler import handle_rotation_check
from cogs.gear import _resolve_character, _try_auto_register, _chunks
from db.server_config import log_usage, check_rate_limit, get_guild_config

log = logging.getLogger(__name__)


class RotationCog(commands.Cog, name="Rotation"):
    """Cast-by-cast rotation anomaly checks."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _run(
        self,
        interaction: discord.Interaction,
        character: str,
        spec: str | None,
        report: str | None,
        fight: int | None,
    ) -> None:
        guild_id = str(interaction.guild_id)

        # If the user passed a specific report, validate it up front so a typo
        # gets an instant reply instead of a 15s defer ending in a WCL error.
        if report:
            from core.rotation_handler import parse_report_ref
            code, _f = parse_report_ref(report)
            if not code:
                await interaction.response.send_message(
                    "That doesn't look like a Warcraft Logs report link or code. "
                    "Paste the full URL or the 16+ character report code, or omit it "
                    "to use their most recent log.",
                    ephemeral=True,
                )
                return

        allowed, _ = check_rate_limit(guild_id)
        if not allowed:
            await interaction.response.send_message(
                "This server has hit the free plan daily limit (20 commands). "
                "Upgrade to Pro for unlimited usage — use `/subscribe`.",
                ephemeral=True,
            )
            return

        display, reg_spec, realm, region = _resolve_character(character, guild_id)
        auto_note = None
        if display is None:
            # Not in the registry. Try a WCL auto-register first (gets spec+realm).
            auto_result = await _try_auto_register(
                character, guild_id, added_by=str(interaction.user.id)
            )
            if auto_result is not None:
                display, reg_spec, realm, region, auto_note = auto_result
            else:
                # Couldn't auto-register (e.g. no character endpoint hit). Still try
                # the check by log lookup using guild defaults — the handler finds the
                # log and derives the spec from the actual pull. Beats a registry dump.
                gcfg = get_guild_config(guild_id) or {}
                display = character
                reg_spec = None
                realm = gcfg.get("server_slug") or config.DEFAULT_REALM
                region = gcfg.get("region") or "us"

        resolved_spec = spec or reg_spec
        await interaction.response.defer(thinking=True)
        log_usage(guild_id, str(interaction.user.id), "rotationcheck")

        loop = asyncio.get_running_loop()
        try:
            result_text = await loop.run_in_executor(
                None,
                lambda: handle_rotation_check(
                    character=display,
                    spec=resolved_spec,
                    realm=realm,
                    region=region or "us",
                    guild_id=guild_id,
                    report=report,
                    fight=fight,
                ),
            )
        except Exception as exc:
            log.exception("rotationcheck failed for %s", display)
            result_text = f"Rotation check failed for **{display}**: {exc}"

        if auto_note:
            result_text = result_text + "\n\n" + auto_note

        try:
            for chunk in _chunks(result_text):
                await asyncio.wait_for(interaction.followup.send(chunk), timeout=15)
        except asyncio.TimeoutError:
            log.error("followup.send timed out for rotationcheck %s", display)
            try:
                await interaction.followup.send(
                    f"That took too long to send for **{display}** — Warcraft Logs "
                    f"may be slow right now. Give it a moment and try again.",
                    ephemeral=True,
                )
            except Exception:
                pass

    # -----------------------------------------------------------------------
    # /rotationcheck — slash command
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="rotationcheck",
        description="Check a caster's cast list for accidental low-rank casts and off-rotation spells.",
    )
    @app_commands.describe(
        character="Character name",
        spec="Override spec (e.g. ele, destro, spriest). Uses registered spec if omitted.",
        report="Optional WCL report link or code to check a specific log (defaults to most recent).",
        fight="Optional fight ID within the report (defaults to the longest pull they're in).",
    )
    async def slash_rotationcheck(
        self,
        interaction: discord.Interaction,
        character: str,
        spec: str | None = None,
        report: str | None = None,
        fight: int | None = None,
    ) -> None:
        await self._run(interaction, character, spec, report, fight)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RotationCog(bot))
