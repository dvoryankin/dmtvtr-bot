from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot, Router
from aiogram.types import Message

router = Router()

# Hardcoded: notify @pchellovod about gets in БRT
_NOTIFY_USER_ID = 2414729
_WATCH_CHAT_ID = -1003681962162

# {get_number: last threshold that was notified; 0 means the get itself was announced}
_notified: dict[int, int] = {}

_THRESHOLDS = [100, 15, 5]  # notify at these remaining counts
_BEAUTIFUL_SUFFIX_WIDTH = 5


def is_beautiful(n: int) -> bool:
    """Numbers ending with five equal digits: 77777, 133333, 222222, etc."""
    s = str(n)
    return len(s) >= _BEAUTIFUL_SUFFIX_WIDTH and len(set(s[-_BEAUTIFUL_SUFFIX_WIDTH:])) == 1


def next_beautiful(after: int) -> int:
    """Find the next message-id with a beautiful repeated-digit suffix."""
    suffix_base = 10 ** _BEAUTIFUL_SUFFIX_WIDTH
    repeated_factor = int("1" * _BEAUTIFUL_SUFFIX_WIDTH)
    start_prefix = max(0, after // suffix_base)
    candidates: list[int] = []
    for prefix in range(start_prefix, start_prefix + 2):
        for digit in range(1, 10):
            n = prefix * suffix_base + digit * repeated_factor
            if n > after and is_beautiful(n):
                candidates.append(n)
    return min(candidates) if candidates else 0


def notification_threshold(remaining: int, previous_threshold: int | None) -> int | None:
    """Return the most specific newly crossed threshold."""
    for threshold in sorted(_THRESHOLDS):
        if remaining <= threshold and (previous_threshold is None or previous_threshold > threshold):
            return threshold
    return None


def message_link(chat_id: int, message_id: int) -> str | None:
    """Build a t.me/c link for private supergroups."""
    chat_id_str = str(abs(chat_id))
    if not chat_id_str.startswith("100"):
        return None
    return f"https://t.me/c/{chat_id_str[3:]}/{message_id}"


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
        is_get = is_beautiful(msg_id)
        nxt = msg_id if is_get else next_beautiful(msg_id)
        if is_get:
            if _notified.get(nxt) == 0:
                return result
            _notified[nxt] = 0
        else:
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

        link = message_link(event.chat.id, msg_id)
        if is_get:
            text = f"🥳 Поздравляем! Сообщение №{nxt}"
            if link:
                text += f":\n\n— {link}"
        else:
            chat_title = getattr(event.chat, "title", None) or "БRT"
            text = (
                f"🎯 Гет {nxt} приближается!\n"
                f"Чат: {chat_title}\n"
                f"Сейчас: {msg_id} (осталось ~{nxt - msg_id})"
            )

        try:
            await bot.send_message(chat_id=_NOTIFY_USER_ID, text=text)
        except Exception:
            logging.warning("Failed to DM user %s about get", _NOTIFY_USER_ID, exc_info=True)

        return result
