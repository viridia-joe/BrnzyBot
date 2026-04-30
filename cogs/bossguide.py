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
    """Split text into Discord-safe chunks."""
    if len(text) <= limit:
        return [text]
    parts = []
    while text:
        parts.append(text[:limit])
        text = text[limit:]
    return parts


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
        for key, display in BOSS_DISPLAY_ORDER:
            if not current_lower or current_lower in display.lower() or current_lower in key:
                choices.append(app_commands.Choice(name=display, value=key))
        return choices[:25]

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
        await interaction.response.defer(thinking=True)

        # Validate boss name up front for fast feedback
        boss_key = resolve_boss(boss)
        if boss_key is None:
            from core.bossguide_data import BOSS_DATA
            names = ", ".join(e.full_name for e in BOSS_DATA.values())
            await interaction.followup.send(
                f"**Unknown boss:** `{boss}`\nAvailable: {names}"
            )
            return

        # Gather roster image bytes
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

        # Run handler in thread (LLM + diagram drawing are blocking)
        loop = asyncio.get_running_loop()
        try:
            text, diagram_png = await loop.run_in_executor(
                None,
                lambda: _run_handler(boss_key, image_bytes),
            )
        except Exception as exc:
            log.exception("bossguide handler failed for %s", boss_key)
            await interaction.followup.send(
                f"Assignment generation failed: {exc}\nCheck bot logs for details."
            )
            return

        # Add source note if we used an image
        if image_source:
            text = text + f"\n\n*— auto-assigned{image_source}*"

        # Post text (chunked if long)
        chunks = _chunks(text)
        await interaction.followup.send(chunks[0])
        for chunk in chunks[1:]:
            await interaction.followup.send(chunk)

        # Post diagram if available
        if diagram_png:
            from core.bossguide_data import BOSS_DATA
            entry = BOSS_DATA[boss_key]
            filename = f"{boss_key}_positions.png"
            file = discord.File(fp=io.BytesIO(diagram_png), filename=filename)
            await interaction.followup.send(
                content=f"*Position diagram — {entry.full_name}*",
                file=file,
            )

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
        try:
            text, diagram_png = await loop.run_in_executor(
                None,
                lambda: _run_handler(boss_key, image_bytes),
            )
        except Exception as exc:
            log.exception("prefix bossguide failed for %s", boss_key)
            await thinking_msg.edit(content=f"Assignment generation failed: {exc}")
            return

        chunks = _chunks(text)
        await thinking_msg.edit(content=chunks[0])
        for chunk in chunks[1:]:
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


def _run_handler(boss_key: str, image_bytes: bytes | None):
    """Thin wrapper so lambda captures are clean."""
    from core.bossguide_handler import handle_bossguide
    return handle_bossguide(boss_key, image_bytes)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BossGuideCog(bot))
