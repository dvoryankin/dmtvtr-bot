from __future__ import annotations

import logging
import random
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message, ReactionTypeEmoji

from app.context import AppContext
from ratings.badges import badge_for_rating
from ratings.praise import is_negative_reply_text, is_praise_reply_text


# Chats where the bot must not react to praise/negative words and must not award activity rating.
RATING_DISABLED_CHATS: frozenset[int] = frozenset({
    -1001130903628,
})


def _format_seconds(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours:
        return f"{hours}ч {minutes}м"
    return f"{minutes}м"


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

        # Chats explicitly opted out of the rating system.
        if chat_id in RATING_DISABLED_CHATS:
            return

        # Ignore commands and command-like captions.
        maybe_text = (message.text or message.caption or "").lstrip()
        if maybe_text.startswith("/"):
            return

        # Reply praise (e.g. "класс", "нормс", "+") => +1 to the replied-to user.
        if self._ctx.settings.reply_plus_enabled:
            try:
                is_reply = bool(message.reply_to_message and message.reply_to_message.from_user)
                is_praise = is_praise_reply_text(maybe_text) if is_reply else False
                is_negative = is_negative_reply_text(maybe_text) if is_reply else False
                logging.debug(
                    "Reply check: text=%r is_reply=%s is_praise=%s is_negative=%s from=%s reply_author=%s",
                    maybe_text,
                    is_reply,
                    is_praise,
                    is_negative,
                    message.from_user.id,
                    message.reply_to_message.from_user.id if is_reply else None,
                )

                # Shared handler for vote results.
                async def _handle_vote(vr, to_user, praised_msg_id, label: str):
                    bot: Bot | None = data.get("bot")
                    if vr.ok:
                        profile = await self._ctx.rating.profile(user=to_user)
                        target = f"{to_user.username}" if to_user.username else to_user.full_name
                        shown_delta = vr.display_delta if vr.display_delta is not None else vr.delta
                        sign = f"+{shown_delta}" if shown_delta >= 0 else str(shown_delta)
                        if vr.ghost:
                            text = f"👻 {target} — ничего не произошло..."
                        else:
                            text = f"{sign} {target} → {vr.new_rating} ({profile.badge})"
                        if vr.delta == 55555:
                            text += f"\n\n<b>🎰 {target} — У ВАС РЕЙТИНГ {vr.new_rating}, ВЫ ВЫИГРАЛИ !!!</b>"
                            text += f"\n\nПчеловод передаёт вам: <tg-spoiler>мозги не ебите</tg-spoiler>"
                        if vr.crazy_text:
                            text += f"\n\n<b>🧠 {vr.crazy_text}</b>"
                        if vr.was_reset:
                            text += f"\n\n<b>🔄 {target} — ТЫ ОБНУЛИРОВАН !!!</b>"
                        for ev in vr.events:
                            text += f"\n\n{ev}"
                        await message.reply(text, parse_mode="HTML")
                        if vr.send_sticker and bot is not None:
                            try:
                                sset = await bot.get_sticker_set("likvidacia_blcktlk")
                                if sset.stickers:
                                    sticker = random.choice(sset.stickers)
                                    await message.answer_sticker(sticker.file_id)
                            except Exception:
                                pass
                        if vr.send_xuan_sticker and bot is not None:
                            try:
                                sset = await bot.get_sticker_set("xuan_sol_by_fStikBot")
                                if sset.stickers:
                                    await message.answer_sticker(sset.stickers[0].file_id)
                            except Exception:
                                pass
                        if vr.minigame is not None:
                            mg_text, mg_kb, _mg_key = vr.minigame
                            try:
                                await message.answer(mg_text, reply_markup=mg_kb, parse_mode="HTML")
                            except Exception:
                                pass
                        if bot is not None:
                            try:
                                await bot.set_message_reaction(
                                    chat_id=message.chat.id,
                                    message_id=praised_msg_id,
                                    reaction=[ReactionTypeEmoji(emoji="👎" if vr.delta < 0 else "👍")],
                                )
                            except Exception:
                                pass
                    elif vr.retry_after is not None:
                        target = f"{to_user.username}" if to_user.username else to_user.full_name
                        await message.reply(
                            f"Кулдаун: повторить можно через {_format_seconds(vr.retry_after)}.\n"
                            f"Кому: {target}"
                        )

                # Check vote ban
                from handlers.rating import _vote_bans
                _ban_until = _vote_bans.get(message.from_user.id, 0)
                if _ban_until > time.time():
                    if is_reply and (is_negative or is_praise):
                        from handlers.rating import _should_reply_ban
                        if _should_reply_ban(message.from_user.id):
                            remaining = int(_ban_until - time.time())
                            await message.reply(f"Ты забанен. Осталось {remaining} сек.")
                        return

                # Handle reply-minus.
                if (
                    is_reply
                    and not message.reply_to_message.from_user.is_bot
                    and is_negative
                ):
                    praised_msg_id = message.reply_to_message.message_id
                    to_user = message.reply_to_message.from_user
                    vr = await self._ctx.rating.vote_minus_one(
                        chat_id=message.chat.id,
                        from_user=message.from_user,
                        to_user=to_user,
                    )
                    await _handle_vote(vr, to_user, praised_msg_id, "minus")
                    return

                # Handle reply-plus.
                if (
                    is_reply
                    and not message.reply_to_message.from_user.is_bot
                    and is_praise
                ):
                    praised_msg_id = message.reply_to_message.message_id
                    to_user = message.reply_to_message.from_user
                    vr = await self._ctx.rating.vote_plus_one(
                        chat_id=message.chat.id,
                        from_user=message.from_user,
                        to_user=to_user,
                    )
                    await _handle_vote(vr, to_user, praised_msg_id, "plus")
                    if vr.ok:
                        bot: Bot | None = data.get("bot")
                        if bot is not None:
                            try:
                                cm = await bot.get_chat_member(message.chat.id, to_user.id)
                                if cm.status in {"administrator", "creator"}:
                                    kpd = await self._ctx.rating.kpd_percent(user_id=to_user.id)
                                    badge = badge_for_rating(int(vr.new_rating or 0), kpd_percent=kpd)
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


class GifSpamCleanupMiddleware(BaseMiddleware):
    """Deletes GIF, sticker, and /popov spam from one target user."""

    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx
        self._first_gif_message_by_chat_user: dict[tuple[int, int], int] = {}
        self._gif_counter_by_chat_user: dict[tuple[int, int], int] = {}
        self._last_was_target_gif_by_chat: dict[int, bool] = {}
        self._sticker_chain_by_chat_user: dict[tuple[int, int], list[int]] = {}
        self._blocked_sticker_chains: set[tuple[int, int]] = set()
        self._popov_history_by_chat_user: dict[tuple[int, int], list[tuple[float, int]]] = {}
        self._popov_blocked_until_by_chat_user: dict[tuple[int, int], float] = {}

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        result = await handler(event, data)
        try:
            await self._after(event, data)
        except Exception:
            # Never break updates because of cleanup logic.
            logging.exception("GifSpamCleanupMiddleware failed")
        return result

    async def _after(self, event: Any, data: dict[str, Any]) -> None:
        if not self._ctx.settings.gif_cleanup_enabled:
            return
        if not isinstance(event, Message):
            return

        message: Message = event
        chat_id = message.chat.id
        if message.chat.type not in {"group", "supergroup"}:
            return
        if not message.from_user or message.from_user.is_bot:
            self._last_was_target_gif_by_chat[chat_id] = False
            self._reset_sticker_chains(chat_id)
            return
        is_target_user = self._is_target_user(message)
        if is_target_user:
            await self._cleanup_popov_spam(message, data)
            await self._cleanup_sticker_spam(message, data)
        elif message.sticker is not None:
            self._reset_sticker_chains(chat_id)

        is_gif = self._is_gif_like(message)
        if not is_target_user or not is_gif:
            # Any non-target-gif message breaks the "consecutive GIFs" chain in this chat.
            self._last_was_target_gif_by_chat[chat_id] = False
            return

        key = (chat_id, message.from_user.id)
        threshold = max(1, self._ctx.settings.gif_cleanup_threshold)
        first_id = self._first_gif_message_by_chat_user.get(key)
        if first_id is None:
            self._first_gif_message_by_chat_user[key] = message.message_id
            first_id = message.message_id

        current_count = self._gif_counter_by_chat_user.get(key, 0) + 1
        self._gif_counter_by_chat_user[key] = current_count
        is_first = message.message_id == first_id
        consecutive_spam = self._last_was_target_gif_by_chat.get(chat_id, False) and not is_first
        threshold_spam = current_count > threshold and not is_first
        self._last_was_target_gif_by_chat[chat_id] = True
        if not consecutive_spam and not threshold_spam:
            return

        bot: Bot | None = data.get("bot")
        if bot is None:
            return

        try:
            await bot.delete_message(chat_id=chat_id, message_id=message.message_id)
        except (TelegramForbiddenError, TelegramBadRequest):
            # Missing rights or too old message - ignore.
            return
        except TelegramAPIError:
            return

    async def _cleanup_sticker_spam(self, message: Message, data: dict[str, Any]) -> None:
        key = (message.chat.id, message.from_user.id)
        if message.sticker is None:
            self._sticker_chain_by_chat_user.pop(key, None)
            self._blocked_sticker_chains.discard(key)
            return

        chain = self._sticker_chain_by_chat_user.setdefault(key, [])
        chain.append(message.message_id)
        threshold = max(2, self._ctx.settings.sticker_cleanup_threshold)
        if key in self._blocked_sticker_chains:
            await self._delete_messages(message.chat.id, [message.message_id], data)
            return
        if len(chain) < threshold:
            return

        self._blocked_sticker_chains.add(key)
        await self._delete_messages(message.chat.id, chain[1:], data)

    async def _cleanup_popov_spam(self, message: Message, data: dict[str, Any]) -> None:
        if (message.text or "").split("@", 1)[0].lower() != "/popov":
            return

        key = (message.chat.id, message.from_user.id)
        now = time.monotonic()
        blocked_until = self._popov_blocked_until_by_chat_user.get(key, 0)
        if now < blocked_until:
            await self._delete_messages(message.chat.id, [message.message_id], data)
            return

        cutoff = now - 60
        history = [
            item for item in self._popov_history_by_chat_user.get(key, [])
            if item[0] > cutoff
        ]
        history.append((now, message.message_id))
        self._popov_history_by_chat_user[key] = history

        threshold = max(2, self._ctx.settings.sticker_cleanup_threshold)
        if len(history) < threshold:
            return

        self._popov_blocked_until_by_chat_user[key] = now + 60
        await self._delete_messages(message.chat.id, [message_id for _, message_id in history[1:]], data)

    @staticmethod
    async def _delete_messages(chat_id: int, message_ids: list[int], data: dict[str, Any]) -> None:
        bot: Bot | None = data.get("bot")
        if bot is None:
            return
        for message_id in message_ids:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
            except (TelegramForbiddenError, TelegramBadRequest):
                continue
            except TelegramAPIError:
                continue

    def _reset_sticker_chains(self, chat_id: int) -> None:
        keys = [key for key in self._sticker_chain_by_chat_user if key[0] == chat_id]
        for key in keys:
            self._sticker_chain_by_chat_user.pop(key, None)
            self._blocked_sticker_chains.discard(key)

    def _is_target_user(self, message: Message) -> bool:
        target_user_id = self._ctx.settings.gif_cleanup_target_user_id
        if target_user_id > 0 and message.from_user and message.from_user.id == target_user_id:
            return True

        target_username = self._ctx.settings.gif_cleanup_target_username.strip().lower().lstrip("@")
        username = (message.from_user.username or "").strip().lower()
        return bool(target_username and username == target_username)

    @staticmethod
    def _is_gif_like(message: Message) -> bool:
        if message.animation is not None:
            return True
        if message.document is not None:
            mime = (message.document.mime_type or "").lower()
            if mime == "image/gif":
                return True
            if message.document.file_name and message.document.file_name.lower().endswith(".gif"):
                return True
        return False
