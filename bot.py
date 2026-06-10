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
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from logging.handlers import RotatingFileHandler
from threading import Thread

import discord
from discord.ext import commands

import config
from db.server_config import init_db, purge_expired_intents

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
_LOG_PATH = os.path.expanduser("~/.openclaw/logs/brnzybot.log")
os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        # Rotate at 10MB, keep 5 — /gearprio logs candidate-pool size per call,
        # so a flat file would grow unbounded on the 20GB disk.
        RotatingFileHandler(
            _LOG_PATH, maxBytes=10_000_000, backupCount=5, encoding="utf-8",
        ),
    ],
)
log = logging.getLogger("brnzybot")

# Shared health state, read by the /health HTTP handler. Updated as the bot boots.
_HEALTH: dict = {
    "ready": False,          # set True on on_ready (Discord gateway connected)
    "loaded_cogs": 0,
    "failed_cogs": [],
}

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
        cog_names = [
            "cogs.gear", "cogs.rotation", "cogs.strategy", "cogs.bossguide",
            "cogs.listener", "cogs.admin", "cogs.onboarding", "cogs.billing",
            "cogs.simexport", "cogs.botduel", "cogs.heartbeat", "cogs.audit",
        ]
        # Load each cog independently — one bad import shouldn't take down the
        # whole bot. Failures are recorded so /health can report degraded state.
        for name in cog_names:
            try:
                await self.load_extension(name)
            except Exception:
                _HEALTH["failed_cogs"].append(name)
                log.exception("Failed to load %s — continuing without it", name)
        _HEALTH["loaded_cogs"] = len(cog_names) - len(_HEALTH["failed_cogs"])
        if _HEALTH["failed_cogs"]:
            log.error("Degraded: %d/%d cogs loaded (failed: %s)",
                      _HEALTH["loaded_cogs"], len(cog_names),
                      ", ".join(_HEALTH["failed_cogs"]))
        else:
            log.info("All %d cogs loaded", len(cog_names))

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
        _HEALTH["ready"] = True
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
            # Healthy only when the gateway is connected AND no cog failed to load.
            # The deploy gate (curl -sf) then actually means "the bot is usable",
            # not just "an HTTP server is listening".
            ok = _HEALTH["ready"] and not _HEALTH["failed_cogs"]
            body = json.dumps({
                "status": "ok" if ok else "degraded",
                "service": "brnzybot",
                "ready": _HEALTH["ready"],
                "loaded_cogs": _HEALTH["loaded_cogs"],
                "failed_cogs": _HEALTH["failed_cogs"],
            }).encode()
            self.send_response(200 if ok else 503)
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
