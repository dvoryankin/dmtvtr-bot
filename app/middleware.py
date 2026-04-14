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
                if _ban_until > time.time() and (message.from_user.username or "").lower() != "pchellovod":
                    if is_reply and (is_negative or is_praise):
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
