"""
BrnzyBot Admin Cog — guild configuration commands.

All commands here require Manage Guild permission or administrator.
These are slash-only — admin config doesn't need prefix fallback.

Commands:
    /setup realm <slug> [region]    — set guild's WoW realm
    /verbosity <mode> [channel]     — set channel verbosity
    /response <target> [channel]    — set response target (channel/ephemeral/dm)
    /addchar <name> <spec> [realm]  — register a character
    /removechar <name>              — deregister a character
    /listchars                      — list registered characters
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.classifier import SPEC_ALIASES
import config
from db.server_config import (
    add_character,
    get_character,
    get_guild_config,
    list_characters,
    remove_character,
    set_guild_config,
    set_guild_phase,
    get_guild_phase,
    set_response_target,
    set_verbosity,
)

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
        description="Register a character so BrnzyBot can look them up.",
    )
    @app_commands.describe(
        name="Character name (as it appears in WCL)",
        spec="Spec (e.g. destro, ele, bm, fury). Run /listspecs to see all options.",
        realm="Realm slug. Defaults to guild's configured realm.",
        region="Region: us, eu, kr, tw (default: us)",
    )
    async def addchar(
        self,
        interaction: discord.Interaction,
        name: str,
        spec: str,
        realm: str | None = None,
        region: str = "us",
    ) -> None:
        guild_id = str(interaction.guild_id)

        # Resolve spec alias
        resolved_spec = SPEC_ALIASES.get(spec.lower(), spec.lower())

        # Fall back to guild realm if not specified
        if not realm:
            guild_cfg = get_guild_config(guild_id)
            realm = guild_cfg["server_slug"] if guild_cfg else config.DEFAULT_REALM

        add_character(
            guild_id=guild_id,
            name=name,
            spec=resolved_spec,
            realm=realm.lower(),
            region=region.lower(),
            added_by=str(interaction.user.id),
        )
        await interaction.response.send_message(
            f"Registered **{name}** as `{resolved_spec}` on {realm} ({region.upper()}).\n"
            f"Use `/gearprio {name}` to run the optimizer.",
            ephemeral=True,
        )

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
        # Group aliases by canonical spec
        canonical_to_aliases: dict[str, list[str]] = {}
        for alias, canon in SPEC_ALIASES.items():
            canonical_to_aliases.setdefault(canon, []).append(alias)

        lines = ["**Valid spec aliases for `/addchar`:**", ""]
        for canon, aliases in sorted(canonical_to_aliases.items()):
            lines.append(f"`{canon}` — also: {', '.join(aliases)}")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
