"""
BrnzyBot Gear Cog — slash and prefix command handlers for gear commands.

Handlers are pure dispatch: they receive an Intent (or construct one from
slash command parameters), call the appropriate core function, and post
the result. No business logic lives here.

Commands:
    /gearprio <character> [upgrades|bis] [slots]
    !gearprio <character> [bis|<n>]

    /gearcheck <character> [spec]
    !gearcheck <character> [spec]
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from core import gearprio
from core.classifier import classify
from core.intent import Intent
from core.messages import thinking
from db.server_config import get_character, list_characters

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _resolve_character(
    interaction_or_ctx,
    char_name: str | None,
    guild_id: str,
) -> tuple[str | None, str | None, str | None, str | None]:
    """
    Look up a character in the guild registry.
    Returns (display_name, spec, realm, region) or (None, error_message, None, None).
    """
    if not char_name:
        return None, "No character specified. Try `/gearprio brnz 3` or `/addchar` to register one.", None, None

    row = get_character(guild_id, char_name)
    if not row:
        # Try a fallback list so the user knows what IS registered
        chars = list_characters(guild_id)
        if chars:
            known = ", ".join(f"**{c['display_name']}**" for c in chars)
            return None, f"Unknown character **{char_name}**. Registered: {known}", None, None
        return None, (
            f"Unknown character **{char_name}**. "
            "Use `/addchar` to register characters for this server."
        ), None, None

    return row["display_name"], row["spec"], row["realm"], row["region"]


async def _run_gearprio_async(
    char_name: str,
    spec: str,
    realm: str,
    region: str,
    mode: str,
    max_changes: int,
) -> str:
    """Run the blocking MIP optimizer in a thread pool. Returns the Discord message string."""
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: gearprio.run(
            char_name=char_name,
            spec=spec,
            realm=realm,
            region=region,
            mode=mode,
            max_changes=max_changes,
        ),
    )
    if isinstance(result, str):
        return result   # error message
    return result.to_discord_block()


# ---------------------------------------------------------------------------
# Gear Cog
# ---------------------------------------------------------------------------

class GearCog(commands.Cog, name="Gear"):
    """Gear optimization and analysis commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -----------------------------------------------------------------------
    # /gearprio — slash command
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="gearprio",
        description="Find your best gear upgrades using the MIP optimizer.",
    )
    @app_commands.describe(
        character="Character name (must be registered with /addchar)",
        mode="upgrades = best N swaps over current gear | bis = full theoretical best-in-slot",
        slots="Number of upgrade slots to evaluate (1–10, default 3). Ignored for bis.",
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="upgrades", value="upgrades"),
        app_commands.Choice(name="bis",      value="bis"),
    ])
    async def slash_gearprio(
        self,
        interaction: discord.Interaction,
        character: str,
        mode: str = "upgrades",
        slots: app_commands.Range[int, 1, 10] = 3,
    ) -> None:
        guild_id = str(interaction.guild_id)

        display, spec, realm, region = await _resolve_character(
            interaction, character, guild_id
        )
        if spec is None:
            await interaction.response.send_message(display, ephemeral=True)
            return

        # Acknowledge immediately — optimizer takes 10-30s
        await interaction.response.defer(thinking=True)

        result_text = await _run_gearprio_async(
            char_name=display,
            spec=spec,
            realm=realm,
            region=region or "us",
            mode=mode,
            max_changes=slots,
        )
        await interaction.followup.send(result_text)

    # -----------------------------------------------------------------------
    # !gearprio — prefix command (aliases: !gp, !prio)
    # -----------------------------------------------------------------------
    @commands.command(name="gearprio", aliases=["gp", "prio"])
    async def prefix_gearprio(self, ctx: commands.Context, *args: str) -> None:
        # Reconstruct as if it were typed without the prefix for the classifier
        raw = "gearprio " + " ".join(args)
        intent = classify(raw, source="prefix")

        guild_id = str(ctx.guild.id) if ctx.guild else "dm"

        char_name = intent.character
        mode      = intent.params.get("mode", "upgrades")
        max_chg   = intent.params.get("max_changes", 3)

        display, spec, realm, region = await _resolve_character(ctx, char_name, guild_id)
        if spec is None:
            await ctx.reply(display, mention_author=False)
            return

        # Post thinking message immediately — prefix commands can't defer like slash
        thinking_msg = await ctx.reply(thinking(), mention_author=False)

        result_text = await _run_gearprio_async(
            char_name=display,
            spec=spec,
            realm=realm,
            region=region or "us",
            mode=mode,
            max_changes=max_chg,
        )

        # Edit the thinking message in place — clean, no double post
        await thinking_msg.edit(content=result_text)

    # -----------------------------------------------------------------------
    # /gearcheck — slash command
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="gearcheck",
        description="Get a full gear analysis and upgrade advice for a character.",
    )
    @app_commands.describe(
        character="Character name",
        spec="Override spec (e.g. affliction, destro). Uses registered spec if omitted.",
    )
    async def slash_gearcheck(
        self,
        interaction: discord.Interaction,
        character: str,
        spec: str | None = None,
    ) -> None:
        guild_id = str(interaction.guild_id)

        display, reg_spec, realm, region = await _resolve_character(
            interaction, character, guild_id
        )
        if reg_spec is None:
            await interaction.response.send_message(display, ephemeral=True)
            return

        resolved_spec = spec or reg_spec
        await interaction.response.defer(thinking=True)

        loop = asyncio.get_running_loop()
        try:
            from core.gear_handler import handle_gear_question
            result_text = await loop.run_in_executor(
                None,
                lambda: handle_gear_question(
                    character=display,
                    spec=resolved_spec,
                    realm=realm,
                    region=region or "us",
                    question=f"Give me a full gear check for {display}.",
                ),
            )
        except Exception as exc:
            log.exception("gearcheck failed for %s", display)
            result_text = f"Gear check failed for **{display}**: {exc}"

        await interaction.followup.send(result_text)

    # -----------------------------------------------------------------------
    # !gearcheck — prefix command (alias: !gc, !gear)
    # -----------------------------------------------------------------------
    @commands.command(name="gearcheck", aliases=["gc", "gear"])
    async def prefix_gearcheck(self, ctx: commands.Context, *args: str) -> None:
        raw = "gearcheck " + " ".join(args)
        intent = classify(raw, source="prefix")

        guild_id  = str(ctx.guild.id) if ctx.guild else "dm"
        char_name = intent.character
        spec_override = intent.spec

        display, spec, realm, region = await _resolve_character(ctx, char_name, guild_id)
        if spec is None:
            await ctx.reply(display, mention_author=False)
            return

        resolved_spec = spec_override or spec
        thinking_msg  = await ctx.reply(thinking(), mention_author=False)

        loop = asyncio.get_running_loop()
        try:
            from core.gear_handler import handle_gear_question
            result_text = await loop.run_in_executor(
                None,
                lambda: handle_gear_question(
                    character=display,
                    spec=resolved_spec,
                    realm=realm,
                    region=region or "us",
                    question=f"Give me a full gear check for {display}.",
                ),
            )
        except Exception as exc:
            log.exception("gearcheck failed for %s", display)
            result_text = f"Gear check failed for **{display}**: {exc}"

        await thinking_msg.edit(content=result_text)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GearCog(bot))
