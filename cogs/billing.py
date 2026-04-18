"""
BrnzyBot Billing Cog — subscription management, custom weights, GDPR.

Commands:
    /subscribe               — DM payment link to requester
    /subscription            — show this guild's current plan + usage
    /cancel                  — instructions to cancel subscription
    /setweights <spec> <k:v> — save personal stat weight overrides
    /myweights [spec]        — display saved weight overrides
    /clearweights <spec>     — remove personal weight overrides for a spec
    /deletedata              — GDPR hard-delete all data for this guild (admin only)
    /deletemydata            — GDPR hard-delete personal data for the requesting user
"""

from __future__ import annotations

import json
import logging
import os
import re

import discord
from discord import app_commands
from discord.ext import commands

import config
from db.server_config import (
    get_subscription,
    is_pro,
    count_usage_today,
    FREE_DAILY_LIMIT,
    get_user_weights,
    set_user_weights,
    delete_user_weights,
    delete_guild_data,
    delete_user_data,
)

log = logging.getLogger(__name__)

STRIPE_PAYMENT_LINK: str = os.environ.get("STRIPE_PAYMENT_LINK", "")


def _require_manage_guild():
    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            return False
        member = interaction.user
        if isinstance(member, discord.Member):
            return member.guild_permissions.manage_guild
        return False
    return app_commands.check(predicate)


class BillingCog(commands.Cog, name="Billing"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -----------------------------------------------------------------------
    # /subscribe
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="subscribe",
        description="Upgrade this server to BrnzyBot Pro for unlimited usage.",
    )
    async def subscribe(self, interaction: discord.Interaction) -> None:
        guild_id = str(interaction.guild_id)
        if is_pro(guild_id):
            await interaction.response.send_message(
                "This server is already on the **Pro plan**. Use `/subscription` to see details.",
                ephemeral=True,
            )
            return

        link = STRIPE_PAYMENT_LINK or config.__dict__.get("STRIPE_PAYMENT_LINK", "")
        if not link:
            await interaction.response.send_message(
                "Subscriptions aren't enabled yet — check back soon!",
                ephemeral=True,
            )
            return

        msg = (
            f"**BrnzyBot Pro**\n\n"
            f"• Unlimited gear checks + gear prio\n"
            f"• Priority AI queue\n"
            f"• Per-user stat weight overrides\n\n"
            f"[Subscribe here]({link})\n\n"
            f"_Payments are processed by Stripe. "
            f"Your server ID `{guild_id}` is used to activate the subscription._"
        )
        try:
            await interaction.user.send(msg)
            await interaction.response.send_message(
                "I've sent you a DM with the subscription link!", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(msg, ephemeral=True)

    # -----------------------------------------------------------------------
    # /subscription
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="subscription",
        description="Show this server's current plan and daily usage.",
    )
    async def subscription(self, interaction: discord.Interaction) -> None:
        guild_id = str(interaction.guild_id)
        sub      = get_subscription(guild_id)
        used     = count_usage_today(guild_id)
        plan     = sub.get("plan", "free")
        status   = sub.get("status", "active")

        if plan == "pro":
            detail = f"**Plan:** Pro ✓  |  **Status:** {status}\n**Usage today:** {used} (unlimited)"
        else:
            remaining = max(0, FREE_DAILY_LIMIT - used)
            bar_filled = min(used, FREE_DAILY_LIMIT)
            bar = "█" * bar_filled + "░" * (FREE_DAILY_LIMIT - bar_filled)
            detail = (
                f"**Plan:** Free  |  **Daily limit:** {FREE_DAILY_LIMIT}/day\n"
                f"**Used today:** {used} / {FREE_DAILY_LIMIT}  ({remaining} remaining)\n"
                f"`{bar}`\n\n"
                f"Upgrade with `/subscribe` for unlimited usage."
            )

        await interaction.response.send_message(detail, ephemeral=True)

    # -----------------------------------------------------------------------
    # /cancel
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="cancel",
        description="Cancel your BrnzyBot Pro subscription.",
    )
    async def cancel(self, interaction: discord.Interaction) -> None:
        guild_id = str(interaction.guild_id)
        if not is_pro(guild_id):
            await interaction.response.send_message(
                "This server isn't on the Pro plan — nothing to cancel.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "To cancel your subscription, log in to the Stripe customer portal:\n"
            "https://billing.stripe.com/p/login/\n\n"
            "Your Pro access continues until the end of the current billing period. "
            "After cancellation, the server reverts to the free plan (20 commands/day).",
            ephemeral=True,
        )

    # -----------------------------------------------------------------------
    # /setweights <spec> stat1:value stat2:value ...
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="setweights",
        description="Save personal stat weight overrides for a spec (Pro only).",
    )
    @app_commands.describe(
        spec="Spec to override (e.g. destro_warlock, fury_warrior)",
        weights="Space-separated stat:value pairs, e.g. spelldamage:1.0 hit:0.8 crit:0.5",
    )
    async def setweights(
        self,
        interaction: discord.Interaction,
        spec: str,
        weights: str,
    ) -> None:
        guild_id = str(interaction.guild_id)
        user_id  = str(interaction.user.id)

        if not is_pro(guild_id):
            await interaction.response.send_message(
                "Custom stat weights are a **Pro** feature. Use `/subscribe` to upgrade.",
                ephemeral=True,
            )
            return

        parsed: dict[str, float] = {}
        for token in weights.split():
            m = re.match(r"^([a-z_]+):([0-9.]+)$", token.lower())
            if not m:
                await interaction.response.send_message(
                    f"Couldn't parse `{token}`. Use format `stat:value` (e.g. `spelldamage:1.0`).",
                    ephemeral=True,
                )
                return
            parsed[m.group(1)] = float(m.group(2))

        if not parsed:
            await interaction.response.send_message("No weights provided.", ephemeral=True)
            return

        set_user_weights(guild_id, user_id, spec.lower(), parsed)
        lines = "\n".join(f"  `{k}`: {v}" for k, v in sorted(parsed.items()))
        await interaction.response.send_message(
            f"Saved weight overrides for **{spec}**:\n{lines}\n\n"
            f"These will be used when you run `/gearcheck` for chars on this spec.",
            ephemeral=True,
        )

    # -----------------------------------------------------------------------
    # /myweights
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="myweights",
        description="Show your saved stat weight overrides.",
    )
    @app_commands.describe(spec="Filter to a specific spec (optional)")
    async def myweights(
        self,
        interaction: discord.Interaction,
        spec: str | None = None,
    ) -> None:
        guild_id = str(interaction.guild_id)
        user_id  = str(interaction.user.id)

        from db.server_config import _conn, DB_PATH
        with _conn(DB_PATH) as conn:
            if spec:
                rows = conn.execute(
                    "SELECT spec, weights_json FROM user_weights WHERE guild_id=? AND user_id=? AND spec=?",
                    (guild_id, user_id, spec.lower()),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT spec, weights_json FROM user_weights WHERE guild_id=? AND user_id=? ORDER BY spec",
                    (guild_id, user_id),
                ).fetchall()

        if not rows:
            await interaction.response.send_message(
                "No custom weights saved. Use `/setweights` to add some (Pro only).",
                ephemeral=True,
            )
            return

        lines = ["**Your custom stat weights:**"]
        for row in rows:
            w = json.loads(row["weights_json"])
            pairs = ", ".join(f"`{k}:{v}`" for k, v in sorted(w.items()))
            lines.append(f"**{row['spec']}** — {pairs}")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    # -----------------------------------------------------------------------
    # /clearweights
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="clearweights",
        description="Remove your saved stat weight overrides for a spec.",
    )
    @app_commands.describe(spec="Spec to clear overrides for")
    async def clearweights(
        self,
        interaction: discord.Interaction,
        spec: str,
    ) -> None:
        guild_id = str(interaction.guild_id)
        user_id  = str(interaction.user.id)

        from db.server_config import _conn, DB_PATH
        with _conn(DB_PATH) as conn:
            conn.execute(
                "DELETE FROM user_weights WHERE guild_id=? AND user_id=? AND spec=?",
                (guild_id, user_id, spec.lower()),
            )
        await interaction.response.send_message(
            f"Cleared custom weights for **{spec}**.", ephemeral=True
        )

    # -----------------------------------------------------------------------
    # /deletedata — full guild wipe (admin only)
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="deletedata",
        description="Permanently delete all BrnzyBot data for this server (GDPR). Cannot be undone.",
    )
    @_require_manage_guild()
    async def deletedata(self, interaction: discord.Interaction) -> None:
        guild_id = str(interaction.guild_id)

        delete_guild_data(guild_id)
        log.info("GDPR guild data deletion for guild %s by user %s", guild_id, interaction.user.id)

        await interaction.response.send_message(
            "All BrnzyBot data for this server has been permanently deleted. "
            "This includes characters, verbosity config, usage logs, and subscriptions.\n\n"
            "If you leave and re-add BrnzyBot, you'll start fresh.",
            ephemeral=True,
        )

    # -----------------------------------------------------------------------
    # /deletemydata — personal data wipe
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="deletemydata",
        description="Permanently delete your personal BrnzyBot data from this server.",
    )
    async def deletemydata(self, interaction: discord.Interaction) -> None:
        guild_id = str(interaction.guild_id)
        user_id  = str(interaction.user.id)

        delete_user_data(guild_id, user_id)
        log.info("GDPR user data deletion for user %s in guild %s", user_id, guild_id)

        await interaction.response.send_message(
            "Your personal data (usage logs, custom weights, characters you registered) "
            "has been permanently deleted from this server's records.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BillingCog(bot))
