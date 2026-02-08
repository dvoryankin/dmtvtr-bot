from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message

from app.context import AppContext
from ratings.badges import badge_for_rating


class ContextMiddleware(BaseMiddleware):
    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        data["ctx"] = self._ctx
        return await handler(event, data)


class ActivityRatingMiddleware(BaseMiddleware):
    """Awards rating points based on regular chat activity (non-command messages)."""

    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx
        self._seen_chats: set[int] = set()

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        finally:
            try:
                await self._after(event, data)
            except Exception:
                # Never break updates because of rating bookkeeping.
                logging.exception("ActivityRatingMiddleware failed")

    async def _after(self, event: Any, data: dict[str, Any]) -> None:
        if not isinstance(event, Message):
            return

        message: Message = event
        if message.chat.type not in {"group", "supergroup"}:
            return
        if not message.from_user or message.from_user.is_bot:
            return

        # Register the chat for scheduled maintenance jobs (sync titles, etc.).
        chat_id = message.chat.id
        if chat_id not in self._seen_chats:
            await self._ctx.rating.touch_chat(
                chat_id=chat_id,
                chat_type=message.chat.type,
                title=getattr(message.chat, "title", None),
                username=getattr(message.chat, "username", None),
            )
            self._seen_chats.add(chat_id)

        # Ignore commands and command-like captions.
        maybe_text = (message.text or message.caption or "").lstrip()
        if maybe_text.startswith("/"):
            return

        # Text messages: avoid counting very short spam.
        if message.text and len(message.text.strip()) < self._ctx.settings.activity_min_chars:
            return

        awarded, new_rating, _retry_after, badge_changed = await self._ctx.rating.award_activity(
            chat_id=message.chat.id,
            user=message.from_user,
        )
        if not awarded or not badge_changed or new_rating is None:
            return

        # If the sender is an admin, try to sync their Telegram admin title to the new badge.
        bot: Bot | None = data.get("bot")
        if bot is None:
            return

        try:
            cm = await bot.get_chat_member(message.chat.id, message.from_user.id)
            if cm.status not in {"administrator", "creator"}:
                return
        except Exception:
            return

        kpd = await self._ctx.rating.kpd_percent(user_id=message.from_user.id)
        badge = badge_for_rating(int(new_rating), kpd_percent=kpd)
        title_with_emoji = f"{badge.icon} {badge.name}"[:16]
        title_plain = f"{badge.name}"[:16]

        try:
            await bot.set_chat_administrator_custom_title(
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                custom_title=title_with_emoji,
            )
        except (TelegramForbiddenError, TelegramBadRequest):
            # Missing permissions or not a supergroup/admin, etc. Ignore silently.
            try:
                # Some chats forbid emojis in admin titles.
                await bot.set_chat_administrator_custom_title(
                    chat_id=message.chat.id,
                    user_id=message.from_user.id,
                    custom_title=title_plain,
                )
            except Exception:
                return
            return
        except TelegramAPIError:
            return
