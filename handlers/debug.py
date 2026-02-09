from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.context import AppContext


router = Router(name="debug")

def _format_seconds(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours:
        return f"{hours}ч {minutes}м"
    return f"{minutes}м"


@router.message(Command("privacy", "botinfo"))
async def cmd_privacy(message: Message, bot: Bot, ctx: AppContext) -> None:
    me = await bot.me()
    can_read_all = bool(getattr(me, "can_read_all_group_messages", False))
    reply_plus_enabled = bool(getattr(ctx.settings, "reply_plus_enabled", 1))

    lines = [
        f"Reply +1 (похвала реплаем): {'ON' if reply_plus_enabled else 'OFF'}",
        f"Privacy mode: {'OFF (бот видит все сообщения)' if can_read_all else 'ON (бот видит только команды/упоминания/ответы боту)'}",
    ]
    if reply_plus_enabled and not can_read_all:
        lines.append(
            "Чтобы работало +1 за обычные слова в reply (без / и без упоминания бота):\n"
            "BotFather → /setprivacy → выбрать бота → Disable."
        )

    await message.answer("\n".join(lines))


@router.message(Command("limits", "cooldowns", "таймауты"))
async def cmd_limits(message: Message, ctx: AppContext) -> None:
    vote_cd = _format_seconds(ctx.settings.vote_cooldown_seconds)
    lines = [
        "Таймауты антиспама рейтинга:",
        f"- /plus и похвала-реплаем (норм/класс/+): 1 раз в {vote_cd} на пару (ты → он) в этом чате",
    ]

    if ctx.settings.activity_points_per_award <= 0:
        lines.append("- Рейтинг за активность: OFF")
    else:
        activity_cd = _format_seconds(ctx.settings.activity_cooldown_seconds)
        lines.append(
            f"- Рейтинг за активность: +{ctx.settings.activity_points_per_award} раз в {activity_cd} (min chars: {ctx.settings.activity_min_chars})"
        )

    await message.answer("\n".join(lines))
