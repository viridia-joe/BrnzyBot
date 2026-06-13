"""
BrnzyBot Heartbeat Cog — posts random content every 8 hours.

Pulls from data/fun_content.json:
  lore   — TBC lore nuggets (100)
  tips   — SSC/TK raid tips (100)
  jokes  — WoW dad jokes (100)
  haikus — WoW ASCII haikus (20+), posted ~once per week

Configure with: /setup heartbeat #channel
"""

from __future__ import annotations

import json
import logging
import os
import random
import time

import discord
from discord.ext import commands, tasks

from db.server_config import (
    get_heartbeat_channel,
    get_last_haiku_ts,
    set_last_haiku_ts,
)

log = logging.getLogger(__name__)

_CONTENT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "fun_content.json"
)

HAIKU_MIN_DAYS   = 5         # never post a haiku within 5 days of the last one
HAIKU_CHANCE     = 0.33      # after 5 days, 33% chance per tick ≈ once per week


class HeartbeatCog(commands.Cog, name="Heartbeat"):
    """Random lore/tip/joke/haiku posts every 8 hours."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot    = bot
        self._pool: dict | None = None
        self._first_tick = True   # first tick after boot may post a deploy changelog
        self.tick.start()

    def cog_unload(self) -> None:
        self.tick.cancel()

    def _content(self) -> dict:
        if self._pool is None:
            try:
                with open(_CONTENT_PATH, encoding="utf-8-sig") as f:
                    self._pool = json.load(f)
            except FileNotFoundError:
                log.warning("fun_content.json not found — heartbeat will be silent")
                self._pool = {"lore": [], "tips": [], "jokes": [], "haikus": []}
        return self._pool

    # ── Background loop ───────────────────────────────────────────────────────

    @tasks.loop(hours=8)
    async def tick(self) -> None:
        pool = self._content()

        # On the first tick after a fresh deploy, post a changelog (New Features /
        # Improvements / Bug Fixes) instead of the usual lore. One-shot: subsequent
        # ticks, and reboots on the same commit, fall through to normal content.
        deploy_msg = None
        if self._first_tick:
            self._first_tick = False
            try:
                from core.changelog import deploy_changelog_if_new
                deploy_msg = deploy_changelog_if_new()
            except Exception as e:
                log.warning("deploy changelog check failed: %s", e)

        if not deploy_msg and not any(pool.values()):
            return

        for guild in self.bot.guilds:
            guild_id   = str(guild.id)
            channel_id = get_heartbeat_channel(guild_id)
            if not channel_id:
                continue
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                continue
            msg = deploy_msg or self._pick(guild_id, pool)
            try:
                await channel.send(msg)
            except discord.HTTPException as e:
                log.warning("Heartbeat post failed for guild %s: %s", guild_id, e)

    @tick.before_loop
    async def _before_tick(self) -> None:
        await self.bot.wait_until_ready()

    # ── Content selection ─────────────────────────────────────────────────────

    def _pick(self, guild_id: str, pool: dict) -> str:
        now         = int(time.time())
        last_haiku  = get_last_haiku_ts(guild_id) or 0
        days_since  = (now - last_haiku) / 86_400

        if pool.get("spammacros") and days_since >= HAIKU_MIN_DAYS and random.random() < HAIKU_CHANCE:
            set_last_haiku_ts(guild_id, now)
            return random.choice(pool["spammacros"])

        category = random.choice(
            [k for k in ("lore", "tips", "jokes") if pool.get(k)]
        )
        item = random.choice(pool[category])

        if category == "lore":
            return f"📜 **Lore of the Burning Crusade**\n{item}"
        elif category == "tips":
            return f"⚔️ **Raid Tip**\n{item}"
        else:
            return f"🎲 {item}"


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HeartbeatCog(bot))
