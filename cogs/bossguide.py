"""
BrnzyBot BossGuide Cog — /bossguide slash command.

Usage:
    /bossguide hydross
    /bossguide "lady vashj" roster:<screenshot>

Behavior:
  - Resolves boss name (fuzzy), calls bossguide_handler for assignments + diagram.
  - If no roster attachment provided, searches last 15 channel messages for an image.
  - Posts assignment text (WoW-ready) + attaches position diagram PNG when available.
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import List

import discord
from discord import app_commands
from discord.ext import commands

from core.bossguide_data import BOSS_DISPLAY_ORDER, resolve_boss
from core.messages import thinking

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chunks(text: str, limit: int = 1990) -> List[str]:
    """Split into Discord-safe chunks (shared impl in core.messages)."""
    from core.messages import chunk
    return chunk(text, limit)


async def _find_recent_image(channel: discord.TextChannel, limit: int = 15) -> bytes | None:
    """Search recent messages for an image attachment. Returns bytes or None."""
    try:
        async for msg in channel.history(limit=limit):
            for att in msg.attachments:
                ctype = att.content_type or ""
                if ctype.startswith("image/") or att.filename.lower().endswith(
                    (".png", ".jpg", ".jpeg", ".gif", ".webp")
                ):
                    return await att.read()
    except Exception as e:
        log.warning("Failed to scan channel history for image: %s", e)
    return None


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class BossGuideCog(commands.Cog, name="BossGuide"):
    """Raid assignment generator for SSC and TK encounters."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -----------------------------------------------------------------------
    # Autocomplete
    # -----------------------------------------------------------------------

    async def _boss_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> List[app_commands.Choice[str]]:
        current_lower = current.lower()
        choices = []
        from core import phase as _phase
        from core.bossguide_data import display_order
        max_phase = _phase.resolve_for_guild(str(interaction.guild_id)).calendar_phase
        for key, display in display_order(max_phase):
            if not current_lower or current_lower in display.lower() or current_lower in key:
                choices.append(app_commands.Choice(name=display, value=key))
        return choices[:25]

    # -----------------------------------------------------------------------
    # Shared handler (called by both /bossguide and /bg)
    # -----------------------------------------------------------------------

    async def _run_bossguide(
        self,
        interaction: discord.Interaction,
        boss: str,
        roster: discord.Attachment = None,
    ) -> None:
        await interaction.response.defer(thinking=True)

        from core import phase as _phase
        from core.bossguide_data import display_order
        max_phase = _phase.resolve_for_guild(str(interaction.guild_id)).calendar_phase
        boss_key = resolve_boss(boss, max_phase=max_phase)
        if boss_key is None:
            names = ", ".join(n for _k, n in display_order(max_phase))
            await interaction.followup.send(
                f"**Unknown boss:** `{boss}`\nAvailable: {names}"
            )
            return

        image_bytes: bytes | None = None
        image_source: str = ""

        if roster is not None:
            try:
                image_bytes = await roster.read()
                image_source = " (using attached roster)"
            except Exception as e:
                log.warning("Failed to read roster attachment: %s", e)

        if image_bytes is None and interaction.channel is not None:
            image_bytes = await _find_recent_image(interaction.channel)
            if image_bytes:
                image_source = " (using recent channel image)"

        loop = asyncio.get_running_loop()
        gid = str(interaction.guild_id)
        try:
            text, diagram_png = await loop.run_in_executor(
                None,
                lambda: _run_handler(boss_key, image_bytes, gid),
            )
        except Exception as exc:
            log.exception("bossguide handler failed for %s", boss_key)
            await interaction.followup.send(
                f"Assignment generation failed: {exc}\nCheck bot logs for details."
            )
            return

        # Split /ra assignment block from plain-text notes at the blank-line boundary
        ra_block, _, notes_block = text.partition("\n\n")
        if not notes_block:
            ra_block = text
            notes_block = ""

        if image_source:
            notes_block = (notes_block + f"\n\n*— auto-assigned{image_source}*").strip()

        for chunk in _chunks(ra_block):
            await interaction.followup.send(chunk)
        if notes_block:
            for chunk in _chunks(notes_block):
                await interaction.followup.send(chunk)

        if diagram_png:
            from core.bossguide_data import BOSS_DATA
            entry = BOSS_DATA[boss_key]
            file = discord.File(fp=io.BytesIO(diagram_png), filename=f"{boss_key}_positions.png")
            await interaction.followup.send(
                content=f"*Position diagram — {entry.full_name}*",
                file=file,
            )

    # -----------------------------------------------------------------------
    # /bossguide
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="bossguide",
        description="Generate WoW-ready raid assignments for an SSC or TK boss.",
    )
    @app_commands.describe(
        boss="Boss name (e.g. hydross, vashj, kaelthas)",
        roster="Optional screenshot of your raid roster for auto-assignment",
    )
    @app_commands.autocomplete(boss=_boss_autocomplete)
    async def slash_bossguide(
        self,
        interaction: discord.Interaction,
        boss: str,
        roster: discord.Attachment = None,
    ) -> None:
        await self._run_bossguide(interaction, boss, roster)

    # -----------------------------------------------------------------------
    # /bg — short alias for /bossguide
    # -----------------------------------------------------------------------

    @app_commands.command(
        name="bg",
        description="Short alias for /bossguide — generate raid assignments for an SSC or TK boss.",
    )
    @app_commands.describe(
        boss="Boss name (e.g. hydross, vashj, kael, kt)",
        roster="Optional screenshot of your raid roster for auto-assignment",
    )
    @app_commands.autocomplete(boss=_boss_autocomplete)
    async def slash_bg(
        self,
        interaction: discord.Interaction,
        boss: str,
        roster: discord.Attachment = None,
    ) -> None:
        await self._run_bossguide(interaction, boss, roster)

    # -----------------------------------------------------------------------
    # !bossguide — prefix fallback
    # -----------------------------------------------------------------------

    @commands.command(name="bossguide", aliases=["guide"])
    async def prefix_bossguide(
        self, ctx: commands.Context, *, boss: str = ""
    ) -> None:
        if not boss:
            await ctx.reply(
                "Usage: `!bossguide <boss>` — e.g. `!bossguide hydross`\n"
                "Bosses: hydross, lurker, morogrim, karathress, leotheras, vashj, "
                "alar, voidreaver, solarian, kaelthas",
                mention_author=False,
            )
            return

        boss_key = resolve_boss(boss)
        if boss_key is None:
            await ctx.reply(f"Unknown boss: `{boss}`", mention_author=False)
            return

        thinking_msg = await ctx.reply(thinking(), mention_author=False)

        # Check for image in command attachments or recent messages
        image_bytes: bytes | None = None
        if ctx.message.attachments:
            try:
                image_bytes = await ctx.message.attachments[0].read()
            except Exception:
                pass
        if image_bytes is None:
            image_bytes = await _find_recent_image(ctx.channel)

        loop = asyncio.get_running_loop()
        gid = str(ctx.guild.id) if ctx.guild else "dm"
        try:
            text, diagram_png = await loop.run_in_executor(
                None,
                lambda: _run_handler(boss_key, image_bytes, gid),
            )
        except Exception as exc:
            log.exception("prefix bossguide failed for %s", boss_key)
            await thinking_msg.edit(content=f"Assignment generation failed: {exc}")
            return

        ra_block, _, notes_block = text.partition("\n\n")
        if not notes_block:
            ra_block = text
            notes_block = ""

        chunks = _chunks(ra_block)
        await thinking_msg.edit(content=chunks[0])
        for chunk in chunks[1:]:
            await thinking_msg.reply(chunk, mention_author=False)
        if notes_block:
            for chunk in _chunks(notes_block):
                await thinking_msg.reply(chunk, mention_author=False)

        if diagram_png:
            from core.bossguide_data import BOSS_DATA
            entry = BOSS_DATA[boss_key]
            file = discord.File(fp=io.BytesIO(diagram_png), filename=f"{boss_key}_positions.png")
            await ctx.reply(
                content=f"*Position diagram — {entry.full_name}*",
                file=file,
                mention_author=False,
            )


def _run_handler(boss_key: str, image_bytes: bytes | None, guild_id: str = "global"):
    """Thin wrapper so lambda captures are clean."""
    from core.bossguide_handler import handle_bossguide
    return handle_bossguide(boss_key, image_bytes, guild_id=guild_id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BossGuideCog(bot))
