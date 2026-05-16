"""
BotDuel state machine — pure logic, no Discord imports.

All public functions return (ok: bool, error_msg: str, duel: dict | None).
"""

from __future__ import annotations

import time
from typing import Optional

from db.server_config import (
    add_ledger_entry,
    create_duel,
    get_duel,
    get_open_duels,
    update_duel,
)

CHALLENGE_TTL = 86_400  # 24 hours


def challenge(
    guild_id: str,
    challenger_id: str,
    opponent_id: str,
    gold_stake: int,
) -> dict:
    now = int(time.time())
    duel_id = create_duel(
        guild_id=guild_id,
        challenger=challenger_id,
        opponent=opponent_id,
        gold_stake=gold_stake,
        created_at=now,
        expires_at=now + CHALLENGE_TTL,
    )
    return get_duel(duel_id)


def accept(
    duel_id: int, guild_id: str, user_id: str
) -> tuple[bool, str, Optional[dict]]:
    duel = get_duel(duel_id, guild_id)
    if duel is None:
        return False, f"Duel #{duel_id} not found.", None
    if duel["status"] != "pending":
        return False, f"Duel #{duel_id} is `{duel['status']}`, not pending.", None
    if duel["opponent"] != user_id:
        return False, "Only the challenged player can accept.", None
    if int(time.time()) > duel["expires_at"]:
        update_duel(duel_id, status="expired")
        return False, "This challenge has expired.", None
    update_duel(duel_id, status="active")
    return True, "", get_duel(duel_id)


def decline(
    duel_id: int, guild_id: str, user_id: str
) -> tuple[bool, str, Optional[dict]]:
    duel = get_duel(duel_id, guild_id)
    if duel is None:
        return False, f"Duel #{duel_id} not found.", None
    if duel["status"] != "pending":
        return False, f"Duel #{duel_id} is `{duel['status']}`, not pending.", None
    if duel["opponent"] != user_id:
        return False, "Only the challenged player can decline.", None
    update_duel(duel_id, status="declined")
    return True, "", get_duel(duel_id)


def report_result(
    duel_id: int, guild_id: str, reporter_id: str, winner_id: str
) -> tuple[bool, str, Optional[dict]]:
    duel = get_duel(duel_id, guild_id)
    if duel is None:
        return False, f"Duel #{duel_id} not found.", None
    if duel["status"] != "active":
        return False, f"Duel #{duel_id} is `{duel['status']}`, not active.", None
    players = {duel["challenger"], duel["opponent"]}
    if reporter_id not in players:
        return False, "Only duel participants can report results.", None
    if winner_id not in players:
        return False, "Winner must be one of the duel participants.", None
    update_duel(duel_id, status="pending_confirm", winner=winner_id, reported_by=reporter_id)
    return True, "", get_duel(duel_id)


def confirm_result(
    duel_id: int, guild_id: str, user_id: str
) -> tuple[bool, str, Optional[dict]]:
    duel = get_duel(duel_id, guild_id)
    if duel is None:
        return False, f"Duel #{duel_id} not found.", None
    if duel["status"] != "pending_confirm":
        return False, f"Duel #{duel_id} is not awaiting confirmation.", None
    players = {duel["challenger"], duel["opponent"]}
    if user_id not in players:
        return False, "Only duel participants can confirm results.", None
    if user_id == duel["reported_by"]:
        return False, "The player who reported can't confirm their own report — ask the other player.", None
    now = int(time.time())
    update_duel(duel_id, status="completed", confirmed_by=user_id, resolved_at=now)
    _settle_ledger(duel, guild_id)
    return True, "", get_duel(duel_id)


def dispute_result(
    duel_id: int, guild_id: str, user_id: str
) -> tuple[bool, str, Optional[dict]]:
    duel = get_duel(duel_id, guild_id)
    if duel is None:
        return False, f"Duel #{duel_id} not found.", None
    if duel["status"] != "pending_confirm":
        return False, f"Duel #{duel_id} is not awaiting confirmation.", None
    players = {duel["challenger"], duel["opponent"]}
    if user_id not in players:
        return False, "Only duel participants can dispute results.", None
    if user_id == duel["reported_by"]:
        return False, "You can't dispute your own report.", None
    update_duel(duel_id, status="disputed")
    return True, "", get_duel(duel_id)


def admin_resolve(
    duel_id: int, guild_id: str, winner_id: str, admin_id: str
) -> tuple[bool, str, Optional[dict]]:
    duel = get_duel(duel_id, guild_id)
    if duel is None:
        return False, f"Duel #{duel_id} not found.", None
    if duel["status"] not in ("disputed", "active", "pending_confirm"):
        return False, f"Duel #{duel_id} is `{duel['status']}` — can't resolve.", None
    players = {duel["challenger"], duel["opponent"]}
    if winner_id not in players:
        return False, "Winner must be one of the duel participants.", None
    now = int(time.time())
    update_duel(duel_id, status="completed", winner=winner_id, confirmed_by=admin_id, resolved_at=now)
    _settle_ledger({**duel, "winner": winner_id}, guild_id)
    return True, "", get_duel(duel_id)


def admin_adjust(guild_id: str, user_id: str, delta: int, reason: str) -> None:
    add_ledger_entry(guild_id, user_id, delta, f"admin_adjust: {reason}", duel_id=None)


def expire_pending(guild_id: str) -> list[int]:
    """Mark all expired PENDING duels; returns list of expired duel IDs."""
    now = int(time.time())
    expired = []
    for d in get_open_duels(guild_id, status="pending"):
        if d["expires_at"] <= now:
            update_duel(d["id"], status="expired")
            expired.append(d["id"])
    return expired


def _settle_ledger(duel: dict, guild_id: str) -> None:
    winner = duel["winner"]
    loser = duel["opponent"] if winner == duel["challenger"] else duel["challenger"]
    stake = duel["gold_stake"]
    duel_id = duel["id"]
    add_ledger_entry(guild_id, winner, +stake, "duel_win", duel_id)
    add_ledger_entry(guild_id, loser, -stake, "duel_loss", duel_id)
