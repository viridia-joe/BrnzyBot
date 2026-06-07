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

    /srprio <character> <raid> [spec]
    !srprio <character> <raid>
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from core.classifier import classify
from core.intent import Intent
from core.messages import thinking
from core.gear_handler import handle_gear_question, handle_gear_list
from core.srprio_handler import handle_srprio, raid_choices
from db.server_config import (
    get_character, list_characters, add_character, get_guild_config,
    log_usage, check_rate_limit,
)

log = logging.getLogger(__name__)

DISCORD_MAX = 2000


def _chunks(text: str, limit: int = DISCORD_MAX) -> list[str]:
    """Split into Discord-safe chunks (shared impl in core.messages)."""
    from core.messages import chunk
    return chunk(text, limit)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_character(
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


async def _try_auto_register(
    char_name: str,
    guild_id: str,
    added_by: str,
) -> tuple[str, str, str, str, str] | None:
    """
    Try to auto-register an unknown character using WCL class data.

    Returns (display_name, spec, realm, region, note) on success, or None if
    WCL lookup fails (character not found, no logs, missing creds, etc.).
    """
    from core.gear_cache import fetch_character_spec, WCL_CLASS_NAME

    guild_cfg = get_guild_config(guild_id)
    if not guild_cfg:
        return None
    realm  = guild_cfg.get("server_slug", config.DEFAULT_REALM)
    region = guild_cfg.get("region", "us")

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None, lambda: fetch_character_spec(char_name, realm, region)
    )
    if result is None:
        return None

    display_name, spec, class_id = result
    class_name = WCL_CLASS_NAME.get(class_id, "Unknown")

    add_character(
        guild_id=guild_id,
        name=display_name,
        spec=spec,
        realm=realm,
        region=region,
        added_by=added_by,
    )
    log.info("Auto-registered %s as %s on %s (%s class %d)",
             display_name, spec, realm, region, class_id)

    note = (
        f"*Auto-registered **{display_name}** as `{spec}` ({class_name} on {realm}) "
        f"based on their latest WCL log. Wrong spec? Run `/addchar {display_name} <spec>` "
        f"— use `/listspecs` for valid options.*"
    )
    return display_name, spec, realm, region, note


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
        description="Get prioritized upgrade advice for a character (AI-powered).",
    )
    @app_commands.describe(
        character="Character name (must be registered with /addchar)",
        spec="Spec override (e.g. elemental, destro, shadow). Uses registered spec if omitted.",
        phase="Phase to optimize for (1–5). Defaults to guild's current phase.",
        arena="Consider rated arena gear (default on). Set false if you don't do arena.",
    )
    async def slash_gearprio(
        self,
        interaction: discord.Interaction,
        character: str,
        spec: str | None = None,
        phase: int | None = None,
        arena: bool = True,
    ) -> None:
        guild_id = str(interaction.guild_id)

        allowed, remaining = check_rate_limit(guild_id)
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
        log_usage(guild_id, str(interaction.user.id), "gearprio")

        _spec_explicit = spec is not None
        loop = asyncio.get_running_loop()
        try:
            result_text = await loop.run_in_executor(
                None,
                lambda: handle_gear_question(
                    character=display,
                    spec=resolved_spec,
                    realm=realm,
                    region=region or "us",
                    question=f"Give me prioritized upgrade advice for {display}.",
                    guild_id=guild_id,
                    phase_override=phase,
                    include_arena=arena,
                    spec_explicit=_spec_explicit,
                ),
            )
        except Exception as exc:
            log.exception("gearprio failed for %s", display)
            result_text = f"Gear priority failed for **{display}**: {exc}"

        if auto_note:
            result_text = result_text + "\n\n" + auto_note

        try:
            for chunk in _chunks(result_text):
                await asyncio.wait_for(interaction.followup.send(chunk), timeout=15)
        except asyncio.TimeoutError:
            log.error("followup.send timed out for gearprio %s", display)

    # -----------------------------------------------------------------------
    # !gearprio — prefix command (aliases: !gp, !prio)
    # -----------------------------------------------------------------------
    @commands.command(name="gearprio", aliases=["gp", "prio"])
    async def prefix_gearprio(self, ctx: commands.Context, *args: str) -> None:
        raw = "gearprio " + " ".join(args)
        intent = classify(raw, source="prefix")

        guild_id  = str(ctx.guild.id) if ctx.guild else "dm"
        char_name = intent.character

        display, spec, realm, region = _resolve_character(char_name, guild_id)
        if display is None:
            await ctx.reply(spec, mention_author=False)
            return

        thinking_msg = await ctx.reply(thinking(), mention_author=False)

        loop = asyncio.get_running_loop()
        try:
            result_text = await loop.run_in_executor(
                None,
                lambda: handle_gear_question(
                    character=display,
                    spec=spec,
                    realm=realm,
                    region=region or "us",
                    question=f"Give me prioritized upgrade advice for {display}.",
                    guild_id=guild_id,
                ),
            )
        except Exception as exc:
            log.exception("gearprio failed for %s", display)
            result_text = f"Gear priority failed for **{display}**: {exc}"

        chunks = _chunks(result_text)
        await thinking_msg.edit(content=chunks[0])
        for chunk in chunks[1:]:
            await thinking_msg.reply(chunk, mention_author=False)

    # -----------------------------------------------------------------------
    # Shared gearcheck runner (used by /gearcheck and /gearcheckv)
    # -----------------------------------------------------------------------

    async def _run_gearcheck(
        self,
        interaction: discord.Interaction,
        character: str,
        spec: str | None,
        verbose: bool,
        phase: int | None = None,
        arena: bool = True,
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
        log_usage(guild_id, str(interaction.user.id), "gearcheck")

        _spec_explicit = spec is not None
        loop = asyncio.get_running_loop()
        try:
            result_text = await loop.run_in_executor(
                None,
                lambda: handle_gear_list(
                    character=display,
                    spec=resolved_spec,
                    realm=realm,
                    region=region or "us",
                    verbose=verbose,
                    guild_id=guild_id,
                    phase_override=phase,
                    include_arena=arena,
                    spec_explicit=_spec_explicit,
                ),
            )
        except Exception as exc:
            log.exception("gearcheck failed for %s", display)
            result_text = f"Gear check failed for **{display}**: {exc}"

        if auto_note:
            result_text = result_text + "\n\n" + auto_note

        try:
            for chunk in _chunks(result_text):
                await asyncio.wait_for(interaction.followup.send(chunk), timeout=15)
        except asyncio.TimeoutError:
            log.error("followup.send timed out for gearcheck %s", display)

    # -----------------------------------------------------------------------
    # /gearcheck — slash command (always verbose: BiS item, EP, % gap per slot)
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="gearcheck",
        description="Head-to-toe gear check vs BiS — shows BiS item, EP, and % gap for every slot.",
    )
    @app_commands.describe(
        character="Character name",
        spec="Override spec (e.g. affliction, destro). Uses registered spec if omitted.",
        phase="Phase to optimize for (1–5). Defaults to guild's current phase.",
        arena="Consider rated arena gear (default on). Set false if you don't do arena.",
    )
    async def slash_gearcheck(
        self,
        interaction: discord.Interaction,
        character: str,
        spec: str | None = None,
        phase: int | None = None,
        arena: bool = True,
    ) -> None:
        await self._run_gearcheck(interaction, character, spec, verbose=True, phase=phase, arena=arena)

    # -----------------------------------------------------------------------
    # !gearcheck — prefix command (alias: !gc, !gear)
    # -----------------------------------------------------------------------
    @commands.command(name="gearcheck", aliases=["gc", "gear"])
    async def prefix_gearcheck(self, ctx: commands.Context, *args: str) -> None:
        await self._prefix_gearcheck_impl(ctx, args, verbose=True)

    async def _prefix_gearcheck_impl(
        self,
        ctx: commands.Context,
        args: tuple,
        verbose: bool,
    ) -> None:
        raw = "gearcheck " + " ".join(args)
        intent = classify(raw, source="prefix")

        guild_id  = str(ctx.guild.id) if ctx.guild else "dm"
        char_name = intent.character
        spec_override = intent.spec

        display, spec, realm, region = _resolve_character(char_name, guild_id)
        auto_note = None
        if display is None:
            auto_result = await _try_auto_register(
                char_name, guild_id, added_by=str(ctx.author.id)
            )
            if auto_result is None:
                await ctx.reply(spec, mention_author=False)
                return
            display, spec, realm, region, auto_note = auto_result

        resolved_spec = spec_override or spec
        thinking_msg  = await ctx.reply(thinking(), mention_author=False)

        loop = asyncio.get_running_loop()
        try:
            result_text = await loop.run_in_executor(
                None,
                lambda: handle_gear_list(
                    character=display,
                    spec=resolved_spec,
                    realm=realm,
                    region=region or "us",
                    verbose=verbose,
                    guild_id=guild_id,
                ),
            )
        except Exception as exc:
            log.exception("gearcheck failed for %s", display)
            result_text = f"Gear check failed for **{display}**: {exc}"

        if auto_note:
            result_text = result_text + "\n\n" + auto_note

        chunks = _chunks(result_text)
        await thinking_msg.edit(content=chunks[0])
        for chunk in chunks[1:]:
            await thinking_msg.reply(chunk, mention_author=False)


    # -----------------------------------------------------------------------
    # /srprio — soft-reserve priority for a specific raid (top 5 upgrades)
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="srprio",
        description="Top-5 items to soft-reserve in a specific raid, ranked by upgrade value.",
    )
    @app_commands.describe(
        character="Character name",
        raid="Raid instance (e.g. Karazhan, Gruul, SSC, TK). Soft reserve is raids only.",
        spec="Override spec. Uses registered spec if omitted.",
        phase="Phase to consider (1–5). Defaults to guild's current phase.",
    )
    async def slash_srprio(
        self,
        interaction: discord.Interaction,
        character: str,
        raid: str,
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
        log_usage(guild_id, str(interaction.user.id), "srprio")

        loop = asyncio.get_running_loop()
        try:
            result_text = await loop.run_in_executor(
                None,
                lambda: handle_srprio(
                    character=display,
                    spec=resolved_spec,
                    realm=realm,
                    raid=raid,
                    region=region or "us",
                    guild_id=guild_id,
                    phase_override=phase,
                ),
            )
        except Exception as exc:
            log.exception("srprio failed for %s", display)
            result_text = f"SR priority failed for **{display}**: {exc}"

        if auto_note:
            result_text = result_text + "\n\n" + auto_note

        try:
            for chunk in _chunks(result_text):
                await asyncio.wait_for(interaction.followup.send(chunk), timeout=15)
        except asyncio.TimeoutError:
            log.error("followup.send timed out for srprio %s", display)

    # -----------------------------------------------------------------------
    # !srprio <character> <raid…> — prefix command (alias: !sr)
    # -----------------------------------------------------------------------
    @commands.command(name="srprio", aliases=["sr"])
    async def prefix_srprio(self, ctx: commands.Context, *args: str) -> None:
        guild_id = str(ctx.guild.id) if ctx.guild else "dm"
        if len(args) < 2:
            await ctx.reply(
                f"Usage: `!srprio <character> <raid>` — raids only ({raid_choices()}).",
                mention_author=False,
            )
            return
        char_name, raid = args[0], " ".join(args[1:])

        display, spec, realm, region = _resolve_character(char_name, guild_id)
        auto_note = None
        if display is None:
            auto_result = await _try_auto_register(
                char_name, guild_id, added_by=str(ctx.author.id)
            )
            if auto_result is None:
                await ctx.reply(spec, mention_author=False)
                return
            display, spec, realm, region, auto_note = auto_result

        thinking_msg = await ctx.reply(thinking(), mention_author=False)
        loop = asyncio.get_running_loop()
        try:
            result_text = await loop.run_in_executor(
                None,
                lambda: handle_srprio(
                    character=display,
                    spec=spec,
                    realm=realm,
                    raid=raid,
                    region=region or "us",
                    guild_id=guild_id,
                ),
            )
        except Exception as exc:
            log.exception("srprio failed for %s", display)
            result_text = f"SR priority failed for **{display}**: {exc}"

        if auto_note:
            result_text = result_text + "\n\n" + auto_note

        chunks = _chunks(result_text)
        await thinking_msg.edit(content=chunks[0])
        for chunk in chunks[1:]:
            await thinking_msg.reply(chunk, mention_author=False)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GearCog(bot))
