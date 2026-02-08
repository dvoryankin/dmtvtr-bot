from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import Message, User

from app.context import AppContext
from ratings.badges import BADGES


router = Router(name="rating")


def _format_seconds(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours:
        return f"{hours}ч {minutes}м"
    return f"{minutes}м"


def _badges_help() -> str:
    lines = ["Доступные лычки (по рейтингу):"]
    for b in BADGES:
        lines.append(f"- {b.icon} {b.name}: {b.threshold}+")
    return "\n".join(lines)


def _normalize_name(name: str) -> str:
    return " ".join((name or "").strip().lower().split())


def _find_badge_by_name(name: str):
    n = _normalize_name(name)
    for b in BADGES:
        if _normalize_name(b.name) == n:
            return b
    return None


async def _is_admin(bot: Bot, *, chat_id: int, user_id: int) -> bool:
    try:
        cm = await bot.get_chat_member(chat_id, user_id)
        return cm.status in {"administrator", "creator"}
    except Exception:
        return False


async def _try_set_admin_title(
    bot: Bot,
    *,
    chat_id: int,
    user_id: int,
    custom_title: str,
) -> tuple[bool, str | None]:
    """Try to set Telegram admin custom title; returns (ok, error_text)."""
    try:
        ok = await bot.set_chat_administrator_custom_title(
            chat_id=chat_id, user_id=user_id, custom_title=custom_title
        )
        return ok, None if ok else "Telegram вернул False"
    except TelegramForbiddenError:
        return False, "боту нужны права администратора (can_promote_members), чтобы менять титулы"
    except TelegramBadRequest as e:
        return False, f"не получилось: {e.message}"
    except TelegramAPIError as e:
        return False, f"ошибка Telegram API: {type(e).__name__}"


async def _sync_title_for_user(
    *,
    bot: Bot,
    ctx: AppContext,
    chat_id: int,
    user: User,
) -> tuple[bool, str | None]:
    profile = await ctx.rating.profile(user=user)
    ok, err = await _try_set_admin_title(
        bot,
        chat_id=chat_id,
        user_id=user.id,
        custom_title=profile.badge,
    )
    return ok, err


@router.message(Command("profile", "rank", "rating"))
async def cmd_profile(message: Message, ctx: AppContext) -> None:
    if not message.from_user:
        return
    p = await ctx.rating.profile(user=message.from_user)
    lines = [
        f"Профиль: {p.display_name}",
        f"Рейтинг: {p.rating}",
        f"Лычка: {p.badge}",
    ]
    if p.next_badge_hint:
        lines.append(p.next_badge_hint)
    await message.answer("\n".join(lines))


@router.message(Command("top", "leaderboard"))
async def cmd_top(message: Message, ctx: AppContext) -> None:
    top = await ctx.rating.top(limit=10)
    if not top:
        await message.answer("Пока пусто. Начни пользоваться ботом или поставь кому-нибудь /plus.")
        return

    lines = ["Топ рейтинга:"]
    for i, p in enumerate(top, start=1):
        lines.append(f"{i}. {p.display_name} — {p.rating} ({p.badge})")
    await message.answer("\n".join(lines))


@router.message(Command("badges", "лычки"))
async def cmd_badges(message: Message) -> None:
    await message.answer(_badges_help())


@router.message(Command("plus", "плюс"))
async def cmd_plus(message: Message, bot: Bot, ctx: AppContext) -> None:
    if not message.from_user:
        return

    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.answer("Ответь на сообщение человека командой /plus.")
        return

    to_user = message.reply_to_message.from_user
    ok, new_rating, retry_after = await ctx.rating.vote_plus_one(
        chat_id=message.chat.id,
        from_user=message.from_user,
        to_user=to_user,
    )
    if not ok:
        if retry_after is None:
            await message.answer("Нельзя поставить /plus самому себе.")
        else:
            await message.answer(f"Слишком часто. Попробуй через {_format_seconds(retry_after)}.")
        return

    profile = await ctx.rating.profile(user=to_user)
    await message.answer(f"+1 {profile.display_name} → {new_rating} ({profile.badge})")

    # If this is a supergroup and both are admins, try to reflect badge as Telegram admin title.
    if message.chat.type in {"group", "supergroup"}:
        ok_title, err = await _sync_title_for_user(
            bot=bot, ctx=ctx, chat_id=message.chat.id, user=to_user
        )
        if not ok_title and err:
            logging.info("Title sync failed: %s", err)


@router.message(Command("title", "титул", "лычка"))
async def cmd_title(message: Message, bot: Bot, ctx: AppContext) -> None:
    if not message.from_user:
        return
    if message.chat.type not in {"group", "supergroup"}:
        await message.answer("Эта команда работает в группе/супергруппе.")
        return
    if not await _is_admin(bot, chat_id=message.chat.id, user_id=message.from_user.id):
        await message.answer("Только админы могут менять титулы.")
        return

    target = message.reply_to_message.from_user if (message.reply_to_message and message.reply_to_message.from_user) else message.from_user
    ok, err = await _sync_title_for_user(bot=bot, ctx=ctx, chat_id=message.chat.id, user=target)
    if ok:
        p = await ctx.rating.profile(user=target)
        await message.answer(f"✅ Титул обновлён: {p.display_name} → {p.badge}")
    else:
        await message.answer(f"❌ Не получилось обновить титул: {err}")


@router.message(Command("synctitles", "sync_titles", "sync_lychki", "синклычки"))
async def cmd_sync_titles(message: Message, bot: Bot, ctx: AppContext) -> None:
    if not message.from_user:
        return
    if message.chat.type not in {"group", "supergroup"}:
        await message.answer("Эта команда работает в группе/супергруппе.")
        return
    if not await _is_admin(bot, chat_id=message.chat.id, user_id=message.from_user.id):
        await message.answer("Только админы могут запускать синхронизацию титулов.")
        return

    admins = await bot.get_chat_administrators(message.chat.id)
    me = await bot.me()

    ok_count = 0
    fail: list[str] = []
    for cm in admins:
        u = cm.user
        if u.is_bot and u.id == me.id:
            continue

        ok, err = await _sync_title_for_user(bot=bot, ctx=ctx, chat_id=message.chat.id, user=u)
        if ok:
            ok_count += 1
        else:
            if err:
                fail.append(f"{u.id}: {err}")

    lines = [f"Готово. Обновлено титулов: {ok_count}."]
    if fail:
        lines.append(f"Ошибок: {len(fail)} (первые 5):")
        for x in fail[:5]:
            lines.append(f"- {x}")
    await message.answer("\n".join(lines))


@router.message(Command("award", "выдать"))
async def cmd_award_badge(message: Message, bot: Bot, ctx: AppContext) -> None:
    """Admin helper: bump rating up to a specific badge threshold and sync title."""
    if not message.from_user:
        return
    if message.chat.type not in {"group", "supergroup"}:
        await message.answer("Эта команда работает в группе/супергруппе.")
        return
    if not await _is_admin(bot, chat_id=message.chat.id, user_id=message.from_user.id):
        await message.answer("Только админы могут выдавать лычки.")
        return

    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.answer("Ответь на сообщение человека: `/award Мыслитель`.\n\n" + _badges_help(), parse_mode="Markdown")
        return

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Укажи лычку: `/award Мыслитель`.\n\n" + _badges_help(), parse_mode="Markdown")
        return

    badge_name = args[1]
    badge = _find_badge_by_name(badge_name)
    if badge is None:
        await message.answer("Не знаю такую лычку.\n\n" + _badges_help())
        return

    target = message.reply_to_message.from_user
    p_before = await ctx.rating.profile(user=target)
    if p_before.rating < badge.threshold:
        delta = badge.threshold - p_before.rating
        new_rating = await ctx.rating.add_points(user=target, delta=delta)
        logging.info("Awarded %s points to %s (new=%s)", delta, target.id, new_rating)

    p_after = await ctx.rating.profile(user=target)
    ok_title, err = await _sync_title_for_user(bot=bot, ctx=ctx, chat_id=message.chat.id, user=target)
    if ok_title:
        await message.answer(f"✅ Выдано: {p_after.display_name} → {p_after.rating} ({p_after.badge})")
    else:
        await message.answer(
            f"✅ Рейтинг обновлён: {p_after.display_name} → {p_after.rating} ({p_after.badge})\n"
            f"❌ Титул не обновился: {err}"
        )
