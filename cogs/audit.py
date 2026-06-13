"""
BrnzyBot Audit Cog — /audit slash command.

Deterministic raid-log Preparation audit (enchants / gems / consumes) for a
Warcraft Logs report. Thin dispatch only: resolve the guild's character registry
into a spec resolver, hand it to core.audit, post the rendered scorecard.

Commands:
    /audit <warcraftlogs-url> [character]
        no character → whole-roster Preparation audit (every registered raider
                       we have a profile for, from the selected fight's pull)
        character     → just that registered raider

No LLM: the audit is fully deterministic. Future prose coaching gates on
config.ENABLE_LLM like every other model site.
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.audit.report import build_audit, build_roster_audit, parse_report_url
from db.server_config import (
    check_rate_limit, get_character, list_characters, log_usage,
)

log = logging.getLogger(__name__)

DISCORD_MAX = 2000


def _chunks(text: str, limit: int = DISCORD_MAX) -> list[str]:
    """Split into Discord-safe chunks (shared impl in core.messages)."""
    from core.messages import chunk
    return chunk(text, limit)


class AuditCog(commands.Cog, name="Audit"):
    """Raid-log Preparation audit."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="audit",
        description="Audit raid prep (enchants/gems/consumes) from a Warcraft Logs report.",
    )
    @app_commands.describe(
        url="Warcraft Logs report URL (optionally with ?fight=N).",
        character="Optional: audit just this registered character instead of the whole roster.",
    )
    async def slash_audit(
        self,
        interaction: discord.Interaction,
        url: str,
        character: str | None = None,
    ) -> None:
        guild_id = str(interaction.guild_id)

        # Validate the report link up front so a typo gets an instant, clear reply
        # instead of a 15-second defer that ends in a circuit-breaker error.
        code, _fight = parse_report_url(url)
        if not code:
            await interaction.response.send_message(
                "That doesn't look like a Warcraft Logs report link. Paste the full "
                "URL, e.g. `https://classic.warcraftlogs.com/reports/aBcD1234EfGh5678`.",
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

        await interaction.response.defer(thinking=True)
        log_usage(guild_id, str(interaction.user.id), "audit")

        # Spec resolver backed by the guild's registry: logged name → canonical spec.
        roster_map = {c["name_lower"]: c["spec"] for c in list_characters(guild_id)}

        def resolve_spec(name: str, wow_class: str) -> str | None:
            return roster_map.get(name.lower())

        loop = asyncio.get_running_loop()
        try:
            if character:
                row = get_character(guild_id, character)
                if not row:
                    await interaction.followup.send(
                        f"Unknown character **{character}** — register with `/addchar` first."
                    )
                    return
                result_text = await loop.run_in_executor(
                    None,
                    lambda: build_audit(url, row["display_name"], row["spec"]).render(),
                )
            else:
                result_text = await loop.run_in_executor(
                    None,
                    lambda: build_roster_audit(url, resolve_spec).render(),
                )
        except Exception as exc:
            log.exception("audit failed")
            result_text = f"Audit failed: {exc}"

        try:
            for chunk in _chunks(result_text):
                await asyncio.wait_for(interaction.followup.send(chunk), timeout=15)
        except asyncio.TimeoutError:
            log.error("followup.send timed out for /audit")
            try:
                await interaction.followup.send(
                    "That audit took too long to send — Warcraft Logs may be slow "
                    "right now. Give it a moment and try again.",
                    ephemeral=True,
                )
            except Exception:
                pass


    # -----------------------------------------------------------------------
    # /raidaudit — whole-night consumable matrix (players × boss kills)
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="raidaudit",
        description="Whole-raid consumable matrix from a WCL report — food, oils, flasks, potions per boss.",
    )
    @app_commands.describe(
        url="Warcraft Logs report URL (a full clear works best).",
    )
    async def slash_raidaudit(
        self,
        interaction: discord.Interaction,
        url: str,
    ) -> None:
        guild_id = str(interaction.guild_id)

        code, _f = parse_report_url(url)
        if not code:
            await interaction.response.send_message(
                "That doesn't look like a Warcraft Logs report link. Paste the full "
                "URL, e.g. `https://classic.warcraftlogs.com/reports/aBcD1234EfGh5678`.",
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

        await interaction.response.defer(thinking=True)
        log_usage(guild_id, str(interaction.user.id), "raidaudit")

        loop = asyncio.get_running_loop()
        try:
            def _build() -> str:
                from core.audit.matrix import gather_raid_matrix
                from core.audit.matrix_render import render_matrix
                return render_matrix(gather_raid_matrix(code))
            result_text = await loop.run_in_executor(None, _build)
        except Exception as exc:
            log.exception("raidaudit failed")
            result_text = f"Raid audit failed: {exc}"

        try:
            for chunk in _chunks(result_text):
                await asyncio.wait_for(interaction.followup.send(chunk), timeout=15)
        except asyncio.TimeoutError:
            log.error("followup.send timed out for /raidaudit")
            try:
                await interaction.followup.send(
                    "That raid audit took too long to send — a full clear is a lot of "
                    "data and Warcraft Logs may be slow. Give it a moment and try again.",
                    ephemeral=True,
                )
            except Exception:
                pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AuditCog(bot))
