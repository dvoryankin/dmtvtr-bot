from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.context import AppContext


router = Router(name="debug")


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

