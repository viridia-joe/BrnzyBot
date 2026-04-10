"""
BrnzyBot Listener Cog — on_message handler.

Responsibilities:
  1. Verbosity gate — decide whether to respond at all based on channel config.
  2. Skip messages that are already handled by prefix/slash commands.
  3. Route natural language gear questions through LLM triage → Intent → handler.
  4. Handle pending intent responses (user answering a clarification question).

Verbosity modes (per guild+channel):
    silent              — never respond unless directly mentioned
    commands_only       — respond to !/slash only, not NL
    speak_when_spoken_to — respond when mentioned (@bot) or commanded (default)
    chatty              — respond to any recognizable gear/raid discussion
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

import config
from core.classifier import classify
from core.intent import Intent
from db.server_config import get_verbosity, pop_pending_intent

log = logging.getLogger(__name__)

# Prefixes that indicate a command already handled by the prefix dispatcher
COMMAND_PREFIXES = ("!", "/")


def _is_command(content: str) -> bool:
    return content.lstrip().startswith(COMMAND_PREFIXES)


def _bot_mentioned(message: discord.Message, bot_user: discord.ClientUser) -> bool:
    return bot_user in message.mentions


def _should_respond(
    verbosity: str,
    message: discord.Message,
    bot_user: discord.ClientUser,
) -> bool:
    """Return True if the bot should process this message given verbosity mode."""
    if verbosity == "silent":
        return _bot_mentioned(message, bot_user)
    if verbosity == "commands_only":
        return False  # prefix/slash cog handles those; NL is ignored
    if verbosity == "speak_when_spoken_to":
        return _bot_mentioned(message, bot_user)
    if verbosity == "chatty":
        return True
    return False


class ListenerCog(commands.Cog, name="Listener"):
    """Natural language message handler and verbosity gate."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # Never respond to ourselves or other bots
        if message.author.bot:
            return

        # Let prefix dispatcher handle commands first
        if _is_command(message.content):
            return

        # DMs: always respond (no verbosity config for DMs)
        if not message.guild:
            await self._handle_nl(message)
            return

        guild_id   = str(message.guild.id)
        channel_id = str(message.channel.id)
        verbosity  = get_verbosity(guild_id, channel_id)

        if not _should_respond(verbosity, message, self.bot.user):
            return

        # Check if this is a response to a pending clarification
        pending = pop_pending_intent(guild_id, channel_id, str(message.author.id))
        if pending:
            intent = Intent.from_dict(pending)
            log.info(
                "Resolved pending intent for %s: command=%s",
                message.author.display_name, intent.command,
            )
            await self._dispatch(message, intent)
            return

        # Route natural language through classifier
        await self._handle_nl(message)

    async def _handle_nl(self, message: discord.Message) -> None:
        """Run NL triage and dispatch resulting intent."""
        content = message.clean_content.strip()
        if not content:
            return

        # Remove bot mention from the front if present
        if self.bot.user and content.startswith(f"@{self.bot.user.display_name}"):
            content = content[len(self.bot.user.display_name) + 1:].strip()

        # Classify in a thread — triage LLM call is blocking
        loop = asyncio.get_running_loop()
        intent = await loop.run_in_executor(
            None,
            lambda: classify(content, source="nl", use_llm=True),
        )

        if not intent.is_executable() or intent.confidence < 0.5:
            log.debug(
                "NL triage: unrecognized or low-confidence (%s, %.2f) — dropping",
                intent.command, intent.confidence,
            )
            return

        if intent.needs_clarification():
            await self._ask_clarification(message, intent)
            return

        await self._dispatch(message, intent)

    async def _ask_clarification(
        self, message: discord.Message, intent: Intent
    ) -> None:
        """Store the pending intent and ask the user for clarification."""
        from db.server_config import store_pending_intent
        guild_id   = str(message.guild.id) if message.guild else "dm"
        channel_id = str(message.channel.id)
        user_id    = str(message.author.id)

        store_pending_intent(
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=user_id,
            intent=intent.to_dict(),
            prompt=intent.clarification,
            ttl_seconds=120,
        )
        await message.reply(intent.clarification, mention_author=False)

    async def _dispatch(self, message: discord.Message, intent: Intent) -> None:
        """Route a resolved intent to the appropriate cog/handler."""
        guild_id = str(message.guild.id) if message.guild else "dm"

        if intent.command == "gearprio":
            # Reuse the prefix_gearprio logic via the Gear cog
            gear_cog = self.bot.get_cog("Gear")
            if not gear_cog:
                return

            from db.server_config import get_character, list_characters
            char_name = intent.character
            mode      = intent.params.get("mode", "upgrades")
            max_chg   = intent.params.get("max_changes", 3)

            if not char_name:
                await message.reply(
                    "Which character? Try `!gearprio brnz 3` or mention a registered name.",
                    mention_author=False,
                )
                return

            row = get_character(guild_id, char_name)
            if not row:
                chars = list_characters(guild_id)
                known = ", ".join(f"**{c['display_name']}**" for c in chars) if chars else "none yet"
                await message.reply(
                    f"I don't have **{char_name}** registered. Known characters: {known}",
                    mention_author=False,
                )
                return

            from core.messages import thinking
            thinking_msg = await message.reply(thinking(), mention_author=False)

            from cogs.gear import _run_gearprio_async
            result_text = await _run_gearprio_async(
                char_name=row["display_name"],
                spec=row["spec"],
                realm=row["realm"],
                region=row.get("region", "us"),
                mode=mode,
                max_changes=max_chg,
            )
            await thinking_msg.edit(content=result_text)

        elif intent.command == "gearcheck":
            gear_cog = self.bot.get_cog("Gear")
            if not gear_cog:
                return
            # Synthesize a fake Context and call the prefix handler
            # (simplest path — avoids duplicating gear_handler invocation logic)
            fake_args = [intent.character or ""]
            if intent.spec:
                fake_args.append(intent.spec)
            # Build a minimal ctx-like object isn't feasible; invoke the logic directly
            from db.server_config import get_character
            row = get_character(guild_id, intent.character or "")
            if not row:
                await message.reply(
                    f"I don't know **{intent.character}**. Use `/addchar` to register them.",
                    mention_author=False,
                )
                return

            from core.messages import thinking as _thinking
            thinking_msg = await message.reply(_thinking(), mention_author=False)

            loop = asyncio.get_running_loop()
            try:
                from core.gear_handler import handle_gear_question
                result_text = await loop.run_in_executor(
                    None,
                    lambda: handle_gear_question(
                        character=row["display_name"],
                        spec=intent.spec or row["spec"],
                        realm=row["realm"],
                        region=row.get("region", "us"),
                        question=f"Give me a full gear check for {row['display_name']}.",
                    ),
                )
            except Exception as exc:
                log.exception("gearcheck dispatch failed")
                result_text = f"Gear check failed: {exc}"

            await thinking_msg.edit(content=result_text)

        else:
            log.debug("Unhandled intent command: %s", intent.command)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ListenerCog(bot))
