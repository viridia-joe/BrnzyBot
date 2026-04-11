"""
BrnzyBot — standalone discord.py bot entry point.

Architecture:
  bot.py          — startup, cog loading, error handling
  config.py       — env vars, paths, model routing
  cogs/gear.py    — /gearprio, /gearcheck commands
  cogs/listener.py — on_message verbosity gate + NL triage
  cogs/admin.py   — /setup, /verbosity, /addchar
  core/           — pure logic (optimizer, cache, classifier, etc.)
  db/             — per-server config SQLite

Usage:
    python bot.py

Requires DISCORD_BOT_TOKEN in ~/.openclaw/data/.env or environment.
"""

import asyncio
import logging
import sys

import discord
from discord.ext import commands

import config
from db.server_config import init_db, purge_expired_intents

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            __import__("os").path.expanduser("~/.openclaw/logs/brnzybot.log"),
            encoding="utf-8",
        ),
    ],
)
log = logging.getLogger("brnzybot")

# ---------------------------------------------------------------------------
# Intents
# ---------------------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True   # Required for prefix commands + NL triage
intents.members = False           # Not needed


# ---------------------------------------------------------------------------
# Bot subclass
# ---------------------------------------------------------------------------
class BrnzyBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=config.COMMAND_PREFIX,
            intents=intents,
            help_command=None,   # We provide our own
        )

    async def setup_hook(self) -> None:
        """Called once before the bot connects. Load cogs and sync slash commands."""
        await self.load_extension("cogs.gear")
        await self.load_extension("cogs.strategy")
        await self.load_extension("cogs.listener")
        await self.load_extension("cogs.admin")
        log.info("Cogs loaded")

        # Sync slash commands globally
        # For faster iteration during dev, use: await self.tree.sync(guild=discord.Object(id=GUILD_ID))
        synced = await self.tree.sync()
        log.info("Slash commands synced: %d", len(synced))

    async def on_ready(self) -> None:
        log.info("BrnzyBot online as %s (id=%s)", self.user, self.user.id)
        # Purge any stale pending intents from a previous session
        purge_expired_intents()

    async def on_error(self, event: str, *args, **kwargs) -> None:
        log.exception("Unhandled error in event %s", event)

    async def on_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        if isinstance(error, commands.CommandNotFound):
            return  # Silently ignore unknown prefix commands — listener handles them
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.reply(
                f"Missing argument: `{error.param.name}`. "
                f"Try `!help {ctx.command}` for usage.",
                mention_author=False,
            )
            return
        log.error("Command error in %s: %s", ctx.command, error)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    missing = config.validate()
    if missing:
        log.error("Missing required config: %s", ", ".join(missing))
        log.error("Set these in ~/.openclaw/data/.env or as environment variables.")
        sys.exit(1)

    # Ensure bot DB is initialized
    init_db()
    log.info("Bot database ready at %s", config.BOT_DB_PATH)

    bot = BrnzyBot()
    bot.run(config.DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
