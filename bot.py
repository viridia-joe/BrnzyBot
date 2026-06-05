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
import json
import logging
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

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
        await self.load_extension("cogs.rotation")
        await self.load_extension("cogs.strategy")
        await self.load_extension("cogs.bossguide")
        await self.load_extension("cogs.listener")
        await self.load_extension("cogs.admin")
        await self.load_extension("cogs.onboarding")
        await self.load_extension("cogs.billing")
        await self.load_extension("cogs.simexport")
        await self.load_extension("cogs.botduel")
        await self.load_extension("cogs.heartbeat")
        log.info("Cogs loaded")

        # Slash-command sync — pick exactly ONE scope per server. If the same
        # command is registered both guild-scoped and globally, both resolve in
        # that guild and Discord lists every command twice (issue #4).
        home = discord.Object(id=config.HOME_GUILD_ID) if config.HOME_GUILD_ID else None
        if config.DEV_GUILD_SYNC and home is not None:
            # Dev: instant home-guild sync, and drop the global set so it can't
            # double up. copy_global_to must run before we clear the globals.
            self.tree.copy_global_to(guild=home)
            synced = await self.tree.sync(guild=home)
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            log.info("Slash commands synced to home guild %d (dev, global cleared): %d",
                     config.HOME_GUILD_ID, len(synced))
        else:
            # Production: global sync only. First clear any guild-scoped copies a
            # previous dev run may have left in the home guild, so they don't
            # linger as duplicates alongside the global set.
            if home is not None:
                self.tree.clear_commands(guild=home)
                await self.tree.sync(guild=home)
            synced = await self.tree.sync()
            log.info("Slash commands synced globally: %d", len(synced))

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

class _HealthHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/health":
            body = json.dumps({"status": "ok", "service": "brnzybot"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


def _start_health_server(port: int = 8081) -> None:
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    Thread(target=server.serve_forever, daemon=True, name="health-server").start()
    log.info("Health endpoint: http://0.0.0.0:%d/health", port)


def main() -> None:
    missing = config.validate()
    if missing:
        log.error("Missing required config: %s", ", ".join(missing))
        log.error("Set these in ~/.openclaw/data/.env or as environment variables.")
        sys.exit(1)

    # Ensure bot DB is initialized
    init_db()
    log.info("Bot database ready at %s", config.BOT_DB_PATH)

    health_port = int(__import__("os").environ.get("HEALTH_PORT", "8081"))
    _start_health_server(health_port)

    bot = BrnzyBot()
    bot.run(config.DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
