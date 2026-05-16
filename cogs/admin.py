"""
BrnzyBot Admin Cog — guild configuration commands.

All commands here require Manage Guild permission or administrator.
These are slash-only — admin config doesn't need prefix fallback.

Commands:
    /setup realm <slug> [region]       — set guild's WoW realm
    /verbosity <mode> [channel]        — set channel verbosity
    /response <target> [channel]       — set response target (channel/ephemeral/dm)
    /addchar <name> [spec] [realm]     — register a character (spec auto-detected from WCL if omitted)
    /removechar <name>                 — deregister a character
    /listchars                         — list registered characters
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.classifier import SPEC_ALIASES, VALID_SPECS, SPEC_BY_CLASS, fuzzy_suggest_spec
from core.gear_cache import fetch_character_spec, WCL_CLASS_NAME
from core.gear_handler import handle_gear_list
import config
from db.server_config import (
    add_character,
    get_character,
    get_guild_config,
    list_characters,
    log_usage,
    remove_character,
    set_botduel_log_channel,
    set_guild_config,
    set_guild_phase,
    get_guild_phase,
    set_officer_role,
    set_response_target,
    set_verbosity,
)

DISCORD_MAX = 2000


def _chunks(text: str, limit: int = DISCORD_MAX) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts = []
    while text:
        if len(text) <= limit:
            parts.append(text)
            break
        split = text.rfind("\n", 0, limit)
        if split == -1:
            split = limit
        parts.append(text[:split])
        text = text[split:].lstrip("\n")
    return parts

log = logging.getLogger(__name__)

VERBOSITY_DESCRIPTIONS = {
    "silent":               "Never respond unless directly @mentioned",
    "commands_only":        "Respond to ! and / commands only; ignore natural language",
    "speak_when_spoken_to": "Respond when @mentioned or commanded (recommended)",
    "chatty":               "Respond to any gear/raid discussion in the channel",
}


def _require_manage_guild():
    """App command check: user must have Manage Guild permission."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            return False
        member = interaction.user
        if isinstance(member, discord.Member):
            return member.guild_permissions.manage_guild
        return False
    return app_commands.check(predicate)


class AdminCog(commands.Cog, name="Admin"):
    """Guild configuration and character management."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -----------------------------------------------------------------------
    # /setup realm
    # -----------------------------------------------------------------------
    setup_group = app_commands.Group(name="setup", description="Configure BrnzyBot for this server")

    @setup_group.command(name="phase", description="Set the current TBC content phase for this guild (1–6).")
    @app_commands.describe(phase="Content phase number (1 = Karazhan, 2 = SSC/TK, etc.)")
    @_require_manage_guild()
    async def setup_phase(self, interaction: discord.Interaction, phase: int) -> None:
        if not 1 <= phase <= 6:
            await interaction.response.send_message("Phase must be between 1 and 6.", ephemeral=True)
            return
        guild_id = str(interaction.guild_id)
        set_guild_phase(guild_id, phase)
        await interaction.response.send_message(
            f"Content phase set to **Phase {phase}**. "
            "Gear recommendations will now filter by phase-appropriate sources.",
            ephemeral=True,
        )

    @setup_group.command(
        name="officerole",
        description="Set the officer role used for CTR duel dispute resolution.",
    )
    @app_commands.describe(role="Role that can resolve disputed duels and adjust gold balances")
    @_require_manage_guild()
    async def setup_officerole(
        self, interaction: discord.Interaction, role: discord.Role
    ) -> None:
        set_officer_role(str(interaction.guild_id), str(role.id))
        await interaction.response.send_message(
            f"Officer role for duel disputes set to {role.mention}.",
            ephemeral=True,
        )

    @setup_group.command(
        name="botduellog",
        description="Set the channel where CTR duel results are logged for bragging rights.",
    )
    @app_commands.describe(channel="Channel that will receive all duel history")
    @_require_manage_guild()
    async def setup_botduellog(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        set_botduel_log_channel(str(interaction.guild_id), str(channel.id))
        await interaction.response.send_message(
            f"CTR duel log channel set to {channel.mention}.",
            ephemeral=True,
        )

    @setup_group.command(name="realm", description="Set the WoW realm slug for this guild.")
    @app_commands.describe(
        slug="Realm slug as it appears in WCL/Armory URLs (e.g. dreamscythe)",
        region="Region: us, eu, kr, tw (default: us)",
    )
    @_require_manage_guild()
    async def setup_realm(
        self,
        interaction: discord.Interaction,
        slug: str,
        region: str = "us",
    ) -> None:
        guild_id   = str(interaction.guild_id)
        guild_name = interaction.guild.name if interaction.guild else guild_id

        set_guild_config(
            guild_id=guild_id,
            guild_name=guild_name,
            server_slug=slug.lower(),
            region=region.lower(),
        )
        await interaction.response.send_message(
            f"Guild realm set to **{slug}** ({region.upper()}). "
            "Characters added via `/addchar` will default to this realm.",
            ephemeral=True,
        )

    # -----------------------------------------------------------------------
    # /verbosity
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="verbosity",
        description="Set how much BrnzyBot talks in this channel.",
    )
    @app_commands.describe(
        mode="Verbosity mode",
        channel="Channel to configure (defaults to current channel)",
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name=f"{k} — {v}", value=k)
        for k, v in VERBOSITY_DESCRIPTIONS.items()
    ])
    @_require_manage_guild()
    async def set_verbosity_cmd(
        self,
        interaction: discord.Interaction,
        mode: str,
        channel: discord.TextChannel | None = None,
    ) -> None:
        guild_id   = str(interaction.guild_id)
        target     = channel or interaction.channel
        channel_id = str(target.id)

        set_verbosity(guild_id, channel_id, mode)
        desc = VERBOSITY_DESCRIPTIONS.get(mode, mode)
        await interaction.response.send_message(
            f"Verbosity for {target.mention} set to **{mode}**.\n_{desc}_",
            ephemeral=True,
        )

    # -----------------------------------------------------------------------
    # /response
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="response",
        description="Set where BrnzyBot posts results in this channel.",
    )
    @app_commands.choices(target=[
        app_commands.Choice(name="channel — visible to everyone", value="channel"),
        app_commands.Choice(name="ephemeral — only visible to requester", value="ephemeral"),
        app_commands.Choice(name="dm — slide into their DMs", value="dm"),
    ])
    @_require_manage_guild()
    async def set_response_cmd(
        self,
        interaction: discord.Interaction,
        target: str,
        channel: discord.TextChannel | None = None,
    ) -> None:
        guild_id   = str(interaction.guild_id)
        ch         = channel or interaction.channel
        channel_id = str(ch.id)

        set_response_target(guild_id, channel_id, target)
        await interaction.response.send_message(
            f"Responses in {ch.mention} will be posted to: **{target}**",
            ephemeral=True,
        )

    # -----------------------------------------------------------------------
    # /addchar
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="addchar",
        description="Register a character. Omit spec to auto-detect from WCL.",
    )
    @app_commands.describe(
        name="Character name (as it appears in WCL)",
        spec="Spec — e.g. tree, ele, fury, shadow. Leave blank to auto-detect from WCL.",
        realm="Realm slug. Defaults to guild's configured realm.",
        region="Region: us, eu, kr, tw (default: us)",
    )
    async def addchar(
        self,
        interaction: discord.Interaction,
        name: str,
        spec: str | None = None,
        realm: str | None = None,
        region: str = "us",
    ) -> None:
        guild_id = str(interaction.guild_id)

        # Fall back to guild realm if not specified
        if not realm:
            guild_cfg = get_guild_config(guild_id)
            realm = guild_cfg["server_slug"] if guild_cfg else config.DEFAULT_REALM
        realm = realm.lower()
        region = region.lower()

        # ── Spec provided: validate before deferring ────────────────────────
        if spec is not None:
            resolved_spec = SPEC_ALIASES.get(spec.lower(), spec.lower())
            if resolved_spec not in VALID_SPECS:
                suggestions = fuzzy_suggest_spec(spec)
                hint = (
                    f"Did you mean: {', '.join(f'`{s}`' for s in suggestions)}?"
                    if suggestions else
                    "Run `/listspecs` to see all valid options."
                )
                await interaction.response.send_message(
                    f"Unknown spec **`{spec}`**. {hint}",
                    ephemeral=True,
                )
                return
            display_name = name
            detected_spec = resolved_spec
            reg_note = (
                f"*Registered **{display_name}** as `{detected_spec}` "
                f"on {realm} ({region.upper()}).*"
            )
        else:
            display_name = None
            detected_spec = None
            reg_note = None

        # Defer publicly — gearcheck result goes to the channel
        await interaction.response.defer(thinking=True)
        loop = asyncio.get_running_loop()

        # ── No spec: auto-detect from WCL ───────────────────────────────────
        if detected_spec is None:
            result = await loop.run_in_executor(
                None, lambda: fetch_character_spec(name, realm, region)
            )
            if result is None:
                await interaction.followup.send(
                    f"Couldn't find **{name}** on WCL for realm `{realm}` ({region.upper()}).\n"
                    f"Try `/addchar {name} <spec>` with a spec — run `/listspecs` for options.",
                    ephemeral=True,
                )
                return
            display_name, detected_spec, class_id = result
            class_name = WCL_CLASS_NAME.get(class_id, "Unknown")
            reg_note = (
                f"*Auto-registered **{display_name}** as `{detected_spec}` "
                f"({class_name} on {realm}) from WCL. "
                f"Wrong spec? `/addchar {display_name} <spec>` — see `/listspecs`.*"
            )

        add_character(
            guild_id=guild_id,
            name=display_name,
            spec=detected_spec,
            realm=realm,
            region=region,
            added_by=str(interaction.user.id),
        )
        log_usage(guild_id, str(interaction.user.id), "addchar")

        # ── Run gearcheck and post result publicly ──────────────────────────
        try:
            result_text = await loop.run_in_executor(
                None,
                lambda: handle_gear_list(
                    character=display_name,
                    spec=detected_spec,
                    realm=realm,
                    region=region or "us",
                    verbose=True,
                    guild_id=guild_id,
                ),
            )
        except Exception as exc:
            log.exception("gearcheck failed after addchar for %s", display_name)
            result_text = f"Registered **{display_name}** but gear check failed: {exc}"

        result_text = result_text + "\n\n" + reg_note
        try:
            for chunk in _chunks(result_text):
                await asyncio.wait_for(interaction.followup.send(chunk), timeout=15)
        except asyncio.TimeoutError:
            log.error("followup timed out for addchar gearcheck %s", display_name)

    # -----------------------------------------------------------------------
    # /removechar
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="removechar",
        description="Remove a registered character.",
    )
    @app_commands.describe(name="Character name to remove")
    async def removechar(self, interaction: discord.Interaction, name: str) -> None:
        guild_id = str(interaction.guild_id)
        removed  = remove_character(guild_id, name)
        if removed:
            await interaction.response.send_message(
                f"**{name}** has been removed.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"**{name}** wasn't registered.", ephemeral=True
            )

    # -----------------------------------------------------------------------
    # /listchars
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="listchars",
        description="List all characters registered for this server.",
    )
    async def listchars(self, interaction: discord.Interaction) -> None:
        guild_id = str(interaction.guild_id)
        chars    = list_characters(guild_id)

        if not chars:
            await interaction.response.send_message(
                "No characters registered yet. Use `/addchar` to add one.",
                ephemeral=True,
            )
            return

        lines = ["**Registered characters:**", ""]
        for c in chars:
            lines.append(
                f"**{c['display_name']}** — `{c['spec']}` on {c['realm']} ({c['region'].upper()})"
            )
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    # -----------------------------------------------------------------------
    # /listspecs — discovery helper
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="listspecs",
        description="Show all valid spec aliases for /addchar.",
    )
    async def listspecs(self, interaction: discord.Interaction) -> None:
        lines = ["**Specs for `/addchar`** — use any alias shown:", ""]
        for class_name, specs in SPEC_BY_CLASS.items():
            lines.append(f"**{class_name}**")
            for canon, aliases in specs:
                lines.append(f"  `{canon}` — {', '.join(aliases)}")
        lines.append("")
        lines.append("_Example: `/addchar Bibblebubble tree` or just `/addchar Bibblebubble` to auto-detect._")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
