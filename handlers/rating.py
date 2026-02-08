from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.context import AppContext


router = Router(name="rating")


def _format_seconds(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours:
        return f"{hours}ч {minutes}м"
    return f"{minutes}м"


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


@router.message(Command("plus", "плюс"))
async def cmd_plus(message: Message, ctx: AppContext) -> None:
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
