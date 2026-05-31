from __future__ import annotations

import logging
import time

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from services.aquastar_service import AquaStarError, get_current_load


router = Router(name="aquastar")

_RATE_LIMIT_REQUESTS = 3
_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_BAN_SECONDS = 10 * 60
_RATE_LIMIT_EXEMPT_USERNAMES = {"pchellovod"}
_request_history: dict[int, list[float]] = {}
_bans: dict[int, float] = {}


def _rate_limit_remaining(user_id: int, *, now: float | None = None) -> int:
    current_time = time.monotonic() if now is None else now
    ban_until = _bans.get(user_id)
    if ban_until is not None:
        if current_time < ban_until:
            return max(1, int(ban_until - current_time))
        _bans.pop(user_id, None)

    cutoff = current_time - _RATE_LIMIT_WINDOW_SECONDS
    recent = [timestamp for timestamp in _request_history.get(user_id, []) if timestamp > cutoff]
    if len(recent) >= _RATE_LIMIT_REQUESTS:
        _request_history.pop(user_id, None)
        _bans[user_id] = current_time + _RATE_LIMIT_BAN_SECONDS
        return _RATE_LIMIT_BAN_SECONDS

    recent.append(current_time)
    _request_history[user_id] = recent
    return 0


@router.message(Command("aquastar", "аквастар", "зал"))
async def cmd_aquastar(message: Message) -> None:
    username = (message.from_user.username or "").lower() if message.from_user is not None else ""
    if message.from_user is not None and username not in _RATE_LIMIT_EXEMPT_USERNAMES:
        remaining = _rate_limit_remaining(message.from_user.id)
        if remaining:
            await message.answer(
                f"Слишком много запросов к AquaStar. Бан на эту команду ещё {remaining} сек."
            )
            return

    try:
        load = await get_current_load()
    except AquaStarError as exc:
        logging.warning("AquaStar API request failed: %s", exc)
        await message.answer("Не удалось получить загруженность AquaStar. Попробуй позже.")
        return

    await message.answer(
        f"🏊 AQUASTAR Павелецкая: сейчас {load.people} посетителей."
    )
