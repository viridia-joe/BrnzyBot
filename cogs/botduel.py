"""
BotDuel cog — Crashin' Thrashin' Robot 1v1 betting system.

Commands:
    /botduel challenge @opponent <gold>  — issue a public challenge
    /botduel accept <id>                 — accept by slash (button fallback)
    /botduel decline <id>                — decline by slash
    /botduel result <id> @winner         — report duel outcome
    /botduel confirm <id>                — confirm the reported result
    /botduel dispute <id>                — contest result; escalates to officers
    /botduel status [id]                 — open duels or single duel detail
    /botduel leaderboard                 — net gold standings
    /botduel record [@player]            — W/L record for a player
    /botduel resolve <id> @winner        — [officer] force-close disputed duel
    /botduel adjust @player <delta> <reason> — [officer] manual gold adjustment

Setup (in /setup):
    /setup officerole @role              — role that can resolve disputes
    /setup botduellog #channel           — channel for duel history log
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

import core.botduel_handler as handler
from db.server_config import (
    get_botduel_log_channel,
    get_duel,
    get_leaderboard,
    get_officer_role,
    get_open_duels,
    get_player_record,
    update_duel,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Persistent button items (survive bot restarts via DynamicItem routing)
# ---------------------------------------------------------------------------

class _AcceptItem(discord.ui.DynamicItem[discord.ui.Button],
                  template=r"duel_accept:(?P<id>[0-9]+)"):
    def __init__(self, duel_id: int) -> None:
        super().__init__(discord.ui.Button(
            label="Accept",
            style=discord.ButtonStyle.success,
            custom_id=f"duel_accept:{duel_id}",
        ))
        self.duel_id = duel_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction,
        item: discord.ui.Button, match: re.Match,  # noqa: F821
    ) -> _AcceptItem:
        return cls(int(match["id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)
        ok, err, duel = handler.accept(self.duel_id, guild_id, user_id)
        if not ok:
            await interaction.response.send_message(err, ephemeral=True)
            return
        await interaction.response.edit_message(
            content=_active_text(duel),
            view=_disabled_view(),
        )
        await _post_log(
            interaction.client, guild_id,
            f"✅ <@{user_id}> accepted the CTR challenge from <@{duel['challenger']}> — "
            f"**{duel['gold_stake']:,}g** stake. Duel #{self.duel_id} is now active!",
        )


class _DeclineItem(discord.ui.DynamicItem[discord.ui.Button],
                   template=r"duel_decline:(?P<id>[0-9]+)"):
    def __init__(self, duel_id: int) -> None:
        super().__init__(discord.ui.Button(
            label="Decline",
            style=discord.ButtonStyle.danger,
            custom_id=f"duel_decline:{duel_id}",
        ))
        self.duel_id = duel_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction,
        item: discord.ui.Button, match: re.Match,  # noqa: F821
    ) -> _DeclineItem:
        return cls(int(match["id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)
        ok, err, duel = handler.decline(self.duel_id, guild_id, user_id)
        if not ok:
            await interaction.response.send_message(err, ephemeral=True)
            return
        await interaction.response.edit_message(
            content=f"~~⚔️ CTR Duel #{self.duel_id}~~ — declined by <@{user_id}>.",
            view=_disabled_view(),
        )
        await _post_log(
            interaction.client, guild_id,
            f"❌ <@{user_id}> declined the CTR challenge from <@{duel['challenger']}>. "
            f"Duel #{self.duel_id} cancelled.",
        )


# Needed for from_custom_id type hint — imported lazily to avoid circular issues
import re  # noqa: E402


# ---------------------------------------------------------------------------
# View / text helpers
# ---------------------------------------------------------------------------

def _challenge_view(duel_id: int) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(_AcceptItem(duel_id))
    view.add_item(_DeclineItem(duel_id))
    return view


def _disabled_view() -> discord.ui.View:
    view = discord.ui.View()
    for label, style in (
        ("Accept", discord.ButtonStyle.success),
        ("Decline", discord.ButtonStyle.danger),
    ):
        btn = discord.ui.Button(label=label, style=style, disabled=True)
        view.add_item(btn)
    return view


def _active_text(duel: dict) -> str:
    return (
        f"⚔️ **CTR Duel #{duel['id']} — ACTIVE**\n"
        f"<@{duel['challenger']}> vs <@{duel['opponent']}> — **{duel['gold_stake']:,}g**\n"
        f"Use `/botduel result {duel['id']} @winner` when the fight is over."
    )


def _duel_detail(duel: dict) -> str:
    lines = [f"**Duel #{duel['id']}**"]
    lines.append(f"<@{duel['challenger']}> vs <@{duel['opponent']}>")
    lines.append(f"Stake: **{duel['gold_stake']:,}g** | Status: `{duel['status']}`")
    if duel.get("winner"):
        lines.append(f"Winner: <@{duel['winner']}>")
    return "\n".join(lines)


async def _post_log(client: discord.Client, guild_id: str, content: str) -> None:
    channel_id = get_botduel_log_channel(guild_id)
    if not channel_id:
        return
    channel = client.get_channel(int(channel_id))
    if channel:
        try:
            await channel.send(content)
        except discord.HTTPException:
            pass


def _is_officer(interaction: discord.Interaction) -> bool:
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.manage_guild:
        return True
    role_id = get_officer_role(str(interaction.guild_id))
    return role_id is not None and any(str(r.id) == role_id for r in member.roles)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class BotDuelCog(commands.Cog, name="BotDuel"):
    """Crashin' Thrashin' Robot 1v1 betting system."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(_AcceptItem, _DeclineItem)

    botduel = app_commands.Group(
        name="botduel",
        description="Crashin' Thrashin' Robot betting system",
    )

    # -----------------------------------------------------------------------
    # /botduel challenge
    # -----------------------------------------------------------------------
    @botduel.command(
        name="challenge",
        description="Challenge another player to a CTR duel for WoW gold.",
    )
    @app_commands.describe(
        opponent="The player you're challenging",
        gold="Gold stake — both players risk this amount",
    )
    async def bd_challenge(
        self,
        interaction: discord.Interaction,
        opponent: discord.Member,
        gold: int,
    ) -> None:
        if opponent.id == interaction.user.id:
            await interaction.response.send_message("You can't challenge yourself.", ephemeral=True)
            return
        if opponent.bot:
            await interaction.response.send_message("You can't challenge a bot.", ephemeral=True)
            return
        if gold < 1:
            await interaction.response.send_message("Gold stake must be at least 1g.", ephemeral=True)
            return

        guild_id = str(interaction.guild_id)
        challenger_id = str(interaction.user.id)
        opponent_id = str(opponent.id)
        duel = handler.challenge(guild_id, challenger_id, opponent_id, gold)
        duel_id = duel["id"]

        content = (
            f"⚔️ **CTR Duel Challenge!**\n"
            f"<@{challenger_id}> has challenged <@{opponent_id}> for **{gold:,}g**!\n"
            f"*{opponent.display_name}: accept or decline below. "
            f"This challenge expires in 24 hours.*\n"
            f"-# Duel #{duel_id}"
        )
        await interaction.response.send_message(content, view=_challenge_view(duel_id))
        msg = await interaction.original_response()
        update_duel(duel_id, message_id=str(msg.id), channel_id=str(interaction.channel_id))

        await _post_log(
            self.bot, guild_id,
            f"⚔️ **Duel #{duel_id} challenge issued** — "
            f"<@{challenger_id}> vs <@{opponent_id}> for **{gold:,}g**",
        )

    # -----------------------------------------------------------------------
    # /botduel accept  (slash fallback when buttons can't be clicked)
    # -----------------------------------------------------------------------
    @botduel.command(name="accept", description="Accept a pending duel challenge.")
    @app_commands.describe(duel_id="Duel ID shown in the challenge message")
    async def bd_accept(self, interaction: discord.Interaction, duel_id: int) -> None:
        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)
        ok, err, duel = handler.accept(duel_id, guild_id, user_id)
        if not ok:
            await interaction.response.send_message(err, ephemeral=True)
            return
        await interaction.response.send_message(
            f"✅ <@{user_id}> accepted! **Duel #{duel_id}** is now active.\n"
            f"<@{duel['challenger']}> vs <@{user_id}> — **{duel['gold_stake']:,}g** stake.\n"
            f"Use `/botduel result {duel_id} @winner` when it's done.",
        )
        await _post_log(
            self.bot, guild_id,
            f"✅ <@{user_id}> accepted the challenge from <@{duel['challenger']}> — "
            f"Duel #{duel_id} active! ({duel['gold_stake']:,}g)",
        )

    # -----------------------------------------------------------------------
    # /botduel decline
    # -----------------------------------------------------------------------
    @botduel.command(name="decline", description="Decline a pending duel challenge.")
    @app_commands.describe(duel_id="Duel ID")
    async def bd_decline(self, interaction: discord.Interaction, duel_id: int) -> None:
        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)
        ok, err, duel = handler.decline(duel_id, guild_id, user_id)
        if not ok:
            await interaction.response.send_message(err, ephemeral=True)
            return
        await interaction.response.send_message(
            f"❌ <@{user_id}> declined duel #{duel_id}. Challenge cancelled.",
        )
        await _post_log(
            self.bot, guild_id,
            f"❌ <@{user_id}> declined the challenge from <@{duel['challenger']}>. "
            f"Duel #{duel_id} cancelled.",
        )

    # -----------------------------------------------------------------------
    # /botduel result
    # -----------------------------------------------------------------------
    @botduel.command(name="result", description="Report the outcome of an active duel.")
    @app_commands.describe(duel_id="Duel ID", winner="The player who won")
    async def bd_result(
        self,
        interaction: discord.Interaction,
        duel_id: int,
        winner: discord.Member,
    ) -> None:
        guild_id = str(interaction.guild_id)
        reporter_id = str(interaction.user.id)
        winner_id = str(winner.id)
        ok, err, duel = handler.report_result(duel_id, guild_id, reporter_id, winner_id)
        if not ok:
            await interaction.response.send_message(err, ephemeral=True)
            return
        loser_id = duel["opponent"] if winner_id == duel["challenger"] else duel["challenger"]
        await interaction.response.send_message(
            f"📝 **Result reported for Duel #{duel_id}**\n"
            f"<@{reporter_id}> says: <@{winner_id}> defeated <@{loser_id}>.\n"
            f"<@{loser_id}>: use `/botduel confirm {duel_id}` to confirm or "
            f"`/botduel dispute {duel_id}` to contest. You have 24 hours.",
        )
        await _post_log(
            self.bot, guild_id,
            f"📝 Duel #{duel_id} result reported by <@{reporter_id}>: "
            f"<@{winner_id}> over <@{loser_id}> ({duel['gold_stake']:,}g) — awaiting confirmation.",
        )

    # -----------------------------------------------------------------------
    # /botduel confirm
    # -----------------------------------------------------------------------
    @botduel.command(name="confirm", description="Confirm the reported result of a duel.")
    @app_commands.describe(duel_id="Duel ID")
    async def bd_confirm(self, interaction: discord.Interaction, duel_id: int) -> None:
        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)
        ok, err, duel = handler.confirm_result(duel_id, guild_id, user_id)
        if not ok:
            await interaction.response.send_message(err, ephemeral=True)
            return
        winner_id = duel["winner"]
        loser_id = duel["opponent"] if winner_id == duel["challenger"] else duel["challenger"]
        stake = duel["gold_stake"]
        w_rec = get_player_record(guild_id, winner_id)
        l_rec = get_player_record(guild_id, loser_id)
        await interaction.response.send_message(
            f"🏆 **Duel #{duel_id} CONFIRMED!**\n"
            f"<@{winner_id}> defeated <@{loser_id}> for **{stake:,}g**!\n"
            f"<@{winner_id}>: {w_rec['wins']}-{w_rec['losses']} | net **{w_rec['net_gold']:+,}g**\n"
            f"<@{loser_id}>: {l_rec['wins']}-{l_rec['losses']} | net **{l_rec['net_gold']:+,}g**",
        )
        await _post_log(
            self.bot, guild_id,
            f"🏆 **DUEL RESULT — #{duel_id}**\n"
            f"<@{winner_id}> ⚔️ <@{loser_id}> | **{stake:,}g** stake\n"
            f"**Winner:** <@{winner_id}> ({w_rec['wins']}-{w_rec['losses']}, net {w_rec['net_gold']:+,}g)\n"
            f"**Loser:** <@{loser_id}> ({l_rec['wins']}-{l_rec['losses']}, net {l_rec['net_gold']:+,}g)",
        )

    # -----------------------------------------------------------------------
    # /botduel dispute
    # -----------------------------------------------------------------------
    @botduel.command(name="dispute", description="Dispute a reported result and request officer review.")
    @app_commands.describe(duel_id="Duel ID")
    async def bd_dispute(self, interaction: discord.Interaction, duel_id: int) -> None:
        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)
        ok, err, duel = handler.dispute_result(duel_id, guild_id, user_id)
        if not ok:
            await interaction.response.send_message(err, ephemeral=True)
            return
        role_id = get_officer_role(guild_id)
        role_ping = f"<@&{role_id}>" if role_id else "Officers"
        await interaction.response.send_message(
            f"⚠️ <@{user_id}> has disputed the result of Duel #{duel_id}.\n"
            f"{role_ping}: use `/botduel resolve {duel_id} @winner` to adjudicate.",
        )
        await _post_log(
            self.bot, guild_id,
            f"⚠️ **Duel #{duel_id} DISPUTED** by <@{user_id}>. "
            f"{role_ping} review required — `/botduel resolve {duel_id} @winner`",
        )

    # -----------------------------------------------------------------------
    # /botduel status
    # -----------------------------------------------------------------------
    @botduel.command(name="status", description="Show open duels or details on a specific duel.")
    @app_commands.describe(duel_id="Duel ID (optional — omit to see all open duels)")
    async def bd_status(
        self,
        interaction: discord.Interaction,
        duel_id: int | None = None,
    ) -> None:
        guild_id = str(interaction.guild_id)
        if duel_id is not None:
            duel = get_duel(duel_id, guild_id)
            if duel is None:
                await interaction.response.send_message(
                    f"Duel #{duel_id} not found.", ephemeral=True
                )
                return
            await interaction.response.send_message(_duel_detail(duel), ephemeral=True)
            return

        open_duels = get_open_duels(guild_id)
        if not open_duels:
            await interaction.response.send_message("No open duels right now.", ephemeral=True)
            return
        lines = ["**Open CTR Duels:**", ""]
        for d in open_duels[:10]:
            lines.append(
                f"**#{d['id']}** — <@{d['challenger']}> vs <@{d['opponent']}> "
                f"| **{d['gold_stake']:,}g** | `{d['status']}`"
            )
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    # -----------------------------------------------------------------------
    # /botduel leaderboard
    # -----------------------------------------------------------------------
    @botduel.command(name="leaderboard", description="Net gold W/L standings for CTR duels.")
    async def bd_leaderboard(self, interaction: discord.Interaction) -> None:
        guild_id = str(interaction.guild_id)
        rows = get_leaderboard(guild_id, limit=10)
        if not rows:
            await interaction.response.send_message("No duel history yet.", ephemeral=True)
            return
        medals = ["🥇", "🥈", "🥉"]
        lines = ["**CTR Duel Leaderboard — Net Gold**", ""]
        for i, row in enumerate(rows):
            medal = medals[i] if i < 3 else f"{i + 1}."
            rec = get_player_record(guild_id, row["user_id"])
            lines.append(
                f"{medal} <@{row['user_id']}> — **{row['net_gold']:+,}g** "
                f"({rec['wins']}W-{rec['losses']}L)"
            )
        await interaction.response.send_message("\n".join(lines))

    # -----------------------------------------------------------------------
    # /botduel record
    # -----------------------------------------------------------------------
    @botduel.command(name="record", description="Show a player's CTR duel W/L record.")
    @app_commands.describe(player="Player to look up (defaults to you)")
    async def bd_record(
        self,
        interaction: discord.Interaction,
        player: discord.Member | None = None,
    ) -> None:
        guild_id = str(interaction.guild_id)
        target = player or interaction.user
        user_id = str(target.id)
        rec = get_player_record(guild_id, user_id)
        await interaction.response.send_message(
            f"**{target.display_name}** CTR Record: "
            f"**{rec['wins']}W-{rec['losses']}L** | "
            f"Net: **{rec['net_gold']:+,}g**",
            ephemeral=(player is None),
        )

    # -----------------------------------------------------------------------
    # /botduel resolve  (officer only)
    # -----------------------------------------------------------------------
    @botduel.command(
        name="resolve",
        description="[Officer] Force-close a disputed duel and declare a winner.",
    )
    @app_commands.describe(duel_id="Duel ID", winner="The player who won")
    async def bd_resolve(
        self,
        interaction: discord.Interaction,
        duel_id: int,
        winner: discord.Member,
    ) -> None:
        if not _is_officer(interaction):
            await interaction.response.send_message(
                "This command requires the officer role or Manage Guild permission.", ephemeral=True
            )
            return
        guild_id = str(interaction.guild_id)
        winner_id = str(winner.id)
        admin_id = str(interaction.user.id)
        ok, err, duel = handler.admin_resolve(duel_id, guild_id, winner_id, admin_id)
        if not ok:
            await interaction.response.send_message(err, ephemeral=True)
            return
        loser_id = duel["opponent"] if winner_id == duel["challenger"] else duel["challenger"]
        await interaction.response.send_message(
            f"⚖️ Duel #{duel_id} resolved by <@{admin_id}>: "
            f"<@{winner_id}> wins ({duel['gold_stake']:,}g).",
        )
        await _post_log(
            self.bot, guild_id,
            f"⚖️ **Admin resolved Duel #{duel_id}** — "
            f"<@{winner_id}> defeats <@{loser_id}> | {duel['gold_stake']:,}g | "
            f"resolved by <@{admin_id}>",
        )

    # -----------------------------------------------------------------------
    # /botduel adjust  (officer only)
    # -----------------------------------------------------------------------
    @botduel.command(
        name="adjust",
        description="[Officer] Manually adjust a player's gold balance.",
    )
    @app_commands.describe(
        player="Player to adjust",
        delta="Amount to adjust (positive to add, negative to subtract)",
        reason="Reason for the adjustment",
    )
    async def bd_adjust(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        delta: int,
        reason: str,
    ) -> None:
        if not _is_officer(interaction):
            await interaction.response.send_message(
                "This command requires the officer role or Manage Guild permission.", ephemeral=True
            )
            return
        guild_id = str(interaction.guild_id)
        user_id = str(player.id)
        admin_id = str(interaction.user.id)
        handler.admin_adjust(guild_id, user_id, delta, reason)
        await interaction.response.send_message(
            f"🔧 Adjusted <@{user_id}>'s balance by **{delta:+,}g** ({reason}).",
            ephemeral=True,
        )
        await _post_log(
            self.bot, guild_id,
            f"🔧 **Admin adjustment** — <@{user_id}> {delta:+,}g | "
            f"Reason: {reason} | By: <@{admin_id}>",
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BotDuelCog(bot))
