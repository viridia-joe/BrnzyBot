"""
BrnzyBot Onboarding Cog — guild join/leave events.

on_guild_join: DMs the server owner with setup instructions.
on_guild_remove: cleans up nothing (data kept for GDPR window).
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

log = logging.getLogger(__name__)

WELCOME_MESSAGE = """
**Hey! BrnzyBot just joined your server.**

I'm a TBC Classic gear optimizer and raid analyst. Here's how to get started:

**1. Set your realm**
`/setup realm <slug>` — e.g. `/setup realm dreamscythe`

**2. Register your characters**
`/addchar <name> <spec>` — e.g. `/addchar Brnz destro`
Use `/listspecs` to see all supported specs.

**3. Run a gear check**
`/gearcheck <name>` — full BIS list with upgrade markers
`/gearprio <name>` — AI-powered upgrade priority advice

**Free plan:** 20 commands per server per day.
**Pro plan:** Unlimited usage + priority queue — `/subscribe`

Questions? Just @mention me in any channel.
""".strip()


class OnboardingCog(commands.Cog, name="Onboarding"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        log.info("Joined guild %s (%s)", guild.name, guild.id)
        owner = guild.owner
        if owner is None:
            try:
                owner = await self.bot.fetch_user(guild.owner_id)
            except Exception:
                log.warning("Could not fetch owner for guild %s", guild.id)
                return

        try:
            await owner.send(WELCOME_MESSAGE)
            log.info("Sent welcome DM to owner %s for guild %s", owner, guild.id)
        except discord.Forbidden:
            log.warning("Cannot DM owner %s (DMs disabled) for guild %s", owner, guild.id)
            # Fall back to system channel if available
            ch = guild.system_channel
            if ch and ch.permissions_for(guild.me).send_messages:
                try:
                    await ch.send(WELCOME_MESSAGE)
                except Exception as e:
                    log.warning("Also failed to post to system channel: %s", e)
        except Exception as e:
            log.exception("Unexpected error sending welcome to guild %s: %s", guild.id, e)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        log.info("Removed from guild %s (%s) — data retained per GDPR window", guild.name, guild.id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(OnboardingCog(bot))
