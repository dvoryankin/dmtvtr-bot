from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot, Router
from aiogram.types import Message

router = Router()

# Hardcoded: notify @pchellovod about gets in БRT
_NOTIFY_USER_ID = 2414729
_WATCH_CHAT_ID = -1003681962162

# {get_number: last_remaining_when_notified}
_notified: dict[int, int] = {}

_THRESHOLDS = [100, 15, 5]  # notify at these remaining counts
_ROUND_GET_STEP = 1000


def is_beautiful(n: int) -> bool:
    """Repdigits only: 77777, 88888, 99999, 111111, etc."""
    s = str(n)
    return len(s) >= 5 and len(set(s)) == 1


def next_beautiful(after: int) -> int:
    """Find the next repdigit after `after`."""
    # Repdigits: 11111, 22222, ..., 99999, 111111, 222222, ...
    # Generate them directly instead of scanning
    for length in range(5, 10):
        for digit in range(1, 10):
            n = int(str(digit) * length)
            if n > after:
                return n
    return 0


def next_round_get(after: int) -> int:
    """Find the next round message-id get."""
    return ((after // _ROUND_GET_STEP) + 1) * _ROUND_GET_STEP


def next_get(after: int) -> int:
    """Find the next tracked get: round thousands or repdigits."""
    candidates = [next_round_get(after)]
    beautiful = next_beautiful(after)
    if beautiful:
        candidates.append(beautiful)
    return min(candidates)


def notification_threshold(remaining: int, previous_threshold: int | None) -> int | None:
    """Return the most specific newly crossed threshold."""
    for threshold in sorted(_THRESHOLDS):
        if remaining <= threshold and (previous_threshold is None or previous_threshold > threshold):
            return threshold
    return None


class GetNotifyMiddleware(BaseMiddleware):
    """Watches message IDs in БRT and DMs @pchellovod when a get is approaching."""

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        result = await handler(event, data)

        if not isinstance(event, Message):
            return result
        if event.chat.id != _WATCH_CHAT_ID:
            return result

        msg_id = event.message_id
        nxt = next_get(msg_id)
        if nxt == 0:
            return result

        remaining = nxt - msg_id

        threshold = notification_threshold(remaining, _notified.get(nxt))
        if threshold is None:
            return result
        _notified[nxt] = threshold

        bot: Bot | None = data.get("bot")
        if bot is None:
            return result

        chat_title = getattr(event.chat, "title", None) or "БRT"
        text = (
            f"🎯 Гет {nxt} приближается!\n"
            f"Чат: {chat_title}\n"
            f"Сейчас: {msg_id} (осталось ~{remaining})"
        )

        try:
            await bot.send_message(chat_id=_NOTIFY_USER_ID, text=text)
        except Exception:
            logging.debug("Failed to DM user %s about get", _NOTIFY_USER_ID)

        return result
