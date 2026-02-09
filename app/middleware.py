from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message, ReactionTypeEmoji

from app.context import AppContext
from ratings.badges import badge_for_rating
from ratings.praise import is_praise_reply_text


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
            logging.info("ActivityMiddleware: event is %s, not Message — skip", type(event).__name__)
            return

        message: Message = event
        logging.info(
            "ActivityMiddleware: msg from=%s chat=%s type=%s text=%r reply=%s",
            message.from_user.id if message.from_user else None,
            message.chat.id,
            message.chat.type,
            (message.text or "")[:50],
            bool(message.reply_to_message),
        )
        if message.chat.type not in {"group", "supergroup"}:
            return
        if not message.from_user:
            return

        # GroupAnonymousBot (id=1087968824): admin posting anonymously.
        # Allow them to give reply-plus, but skip activity rating (can't identify user).
        _ANON_ADMIN_BOT_ID = 1087968824
        is_anon_admin = message.from_user.is_bot and message.from_user.id == _ANON_ADMIN_BOT_ID
        is_regular_bot = message.from_user.is_bot and not is_anon_admin
        if is_regular_bot:
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

        # Reply praise (e.g. "класс", "нормс", "+") => +1 to the replied-to user.
        if self._ctx.settings.reply_plus_enabled:
            try:
                is_reply = bool(message.reply_to_message and message.reply_to_message.from_user)
                is_praise = is_praise_reply_text(maybe_text) if is_reply else False
                logging.debug(
                    "Reply-plus check: text=%r is_reply=%s is_praise=%s from=%s reply_author=%s",
                    maybe_text,
                    is_reply,
                    is_praise,
                    message.from_user.id,
                    message.reply_to_message.from_user.id if is_reply else None,
                )
                if (
                    is_reply
                    and not message.reply_to_message.from_user.is_bot
                    and is_praise
                ):
                    # target = the ORIGINAL message (the one being praised).
                    praised_msg_id = message.reply_to_message.message_id
                    to_user = message.reply_to_message.from_user
                    logging.info(
                        "Reply-plus: from=%s to=%s text=%r praised_msg=%s reply_msg=%s",
                        message.from_user.id,
                        to_user.id,
                        maybe_text,
                        praised_msg_id,
                        message.message_id,
                    )
                    ok, _new_rating, _retry_after = await self._ctx.rating.vote_plus_one(
                        chat_id=message.chat.id,
                        from_user=message.from_user,
                        to_user=to_user,
                    )
                    logging.info(
                        "Reply-plus result: ok=%s new_rating=%s retry=%s",
                        ok, _new_rating, _retry_after,
                    )
                    # Visual confirmation: react on the PRAISED (original) message.
                    bot: Bot | None = data.get("bot")
                    if bot is not None:
                        try:
                            if ok:
                                emoji = "👍"
                            elif _retry_after is None:
                                emoji = "🚫"  # self-vote
                            else:
                                emoji = "⏳"  # cooldown

                            logging.info(
                                "Reply-plus reaction: emoji=%s on msg=%s (NOT on reply msg=%s)",
                                emoji, praised_msg_id, message.message_id,
                            )
                            await bot.set_message_reaction(
                                chat_id=message.chat.id,
                                message_id=praised_msg_id,
                                reaction=[ReactionTypeEmoji(emoji=emoji)],
                            )
                        except Exception:
                            logging.exception("Reply-plus: failed to set reaction")

                    if ok:
                        # Best-effort title sync for admins; ignore failures.
                        if bot is not None:
                            try:
                                cm = await bot.get_chat_member(message.chat.id, to_user.id)
                                if cm.status in {"administrator", "creator"}:
                                    kpd = await self._ctx.rating.kpd_percent(user_id=to_user.id)
                                    badge = badge_for_rating(int(_new_rating or 0), kpd_percent=kpd)
                                    title_with_emoji = f"{badge.icon} {badge.name}"[:16]
                                    title_plain = f"{badge.name}"[:16]
                                    try:
                                        await bot.set_chat_administrator_custom_title(
                                            chat_id=message.chat.id,
                                            user_id=to_user.id,
                                            custom_title=title_with_emoji,
                                        )
                                    except (TelegramForbiddenError, TelegramBadRequest):
                                        await bot.set_chat_administrator_custom_title(
                                            chat_id=message.chat.id,
                                            user_id=to_user.id,
                                            custom_title=title_plain,
                                        )
                            except Exception:
                                pass

                    # Don't award activity points for praise replies (otherwise the voter gains rating too).
                    return
            except Exception:
                # Never break updates because of reply-plus bookkeeping.
                logging.exception("Reply-plus failed")

        # Anonymous admins: can't track identity, skip activity rating.
        if is_anon_admin:
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
