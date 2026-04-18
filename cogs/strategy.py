"""
BrnzyBot Strategy Cog — slash and prefix command handlers for raid strategy questions.

Commands:
    /strat <boss_or_question>     — full strategy for a boss
    !strat <boss_or_question>     — same via prefix
    /abilities <boss>             — list abilities for a boss
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.messages import thinking
from cogs.gear import _chunks

log = logging.getLogger(__name__)


class StrategyCog(commands.Cog, name="Strategy"):
    """Raid strategy and boss mechanic advisor."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -----------------------------------------------------------------------
    # /strat — slash command
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="strat",
        description="Get the raid strategy for a boss or ask a specific mechanic question.",
    )
    @app_commands.describe(
        question="Boss name or question (e.g. 'Prince Malchezaar', 'how do we handle Blast Nova')",
    )
    async def slash_strat(
        self,
        interaction: discord.Interaction,
        question: str,
    ) -> None:
        await interaction.response.defer(thinking=True)

        loop = asyncio.get_running_loop()
        try:
            from core.strategy_handler import handle_strategy_question
            result_text = await loop.run_in_executor(
                None,
                lambda: handle_strategy_question(question),
            )
        except Exception as exc:
            log.exception("strat failed for query: %s", question)
            result_text = f"Strategy lookup failed: {exc}"

        try:
            for chunk in _chunks(result_text):
                await asyncio.wait_for(interaction.followup.send(chunk), timeout=15)
        except asyncio.TimeoutError:
            log.error("followup.send timed out for strat query: %s", question)

    # -----------------------------------------------------------------------
    # /abilities — slash command
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="abilities",
        description="List all abilities and mechanics for a boss.",
    )
    @app_commands.describe(boss="Boss name (e.g. 'Gruul', 'Shade of Aran')")
    async def slash_abilities(
        self,
        interaction: discord.Interaction,
        boss: str,
    ) -> None:
        await interaction.response.defer(thinking=True)

        from core.strategy_context import _build_context
        ctx = _build_context(boss)

        if not ctx.found() or not ctx.abilities:
            await interaction.followup.send(
                f"No ability data found for **{boss}**. "
                "Try the full boss name (e.g. `Prince Malchezaar`, `Gruul the Dragonkiller`)."
            )
            return

        b = ctx.boss
        lines = [f"**{b['name']}** — {b['zone']}", ""]
        for ab in ctx.abilities:
            priority = " ⚠" if ab["important"] else ""
            lines.append(
                f"**{ab['name']}**{priority} [{ab['mechanic_type']}, {ab['targets']}]"
            )
            lines.append(ab["description"])
            lines.append("")

        result_text = "\n".join(lines)
        try:
            for chunk in _chunks(result_text):
                await asyncio.wait_for(interaction.followup.send(chunk), timeout=15)
        except asyncio.TimeoutError:
            log.error("followup.send timed out for abilities query: %s", boss)

    # -----------------------------------------------------------------------
    # !strat — prefix command
    # -----------------------------------------------------------------------
    @commands.command(name="strat", aliases=["strategy", "boss"])
    async def prefix_strat(self, ctx: commands.Context, *, question: str = "") -> None:
        if not question:
            await ctx.reply(
                "Usage: `!strat <boss name or question>` — e.g. `!strat Prince Malchezaar`",
                mention_author=False,
            )
            return

        thinking_msg = await ctx.reply(thinking(), mention_author=False)

        loop = asyncio.get_running_loop()
        try:
            from core.strategy_handler import handle_strategy_question
            result_text = await loop.run_in_executor(
                None,
                lambda: handle_strategy_question(question),
            )
        except Exception as exc:
            log.exception("prefix strat failed for: %s", question)
            result_text = f"Strategy lookup failed: {exc}"

        chunks = _chunks(result_text)
        await thinking_msg.edit(content=chunks[0])
        for chunk in chunks[1:]:
            await thinking_msg.reply(chunk, mention_author=False)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StrategyCog(bot))
