from __future__ import annotations

import os
import logging

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

from app.context import AppContext
from demotivator.trump_tweet import create_trump_tweet_image, download_user_avatar
from utils.asyncio_utils import run_in_thread


router = Router(name="trump")


@router.message(Command("trump", "трамп"))
async def cmd_trump(message: Message, bot: Bot, ctx: AppContext) -> None:
    if not message.from_user:
        return

    if message.reply_to_message:
        original = message.reply_to_message.text or message.reply_to_message.caption
        if not original:
            await message.answer("Нет текста для трампификации")
            return
        user_id = message.reply_to_message.from_user.id if message.reply_to_message.from_user else message.from_user.id
    else:
        raw = (message.text or "").split(maxsplit=1)
        if len(raw) < 2:
            await message.answer("Использование:\n/trump текст\nили ответь на сообщение")
            return
        original = raw[1]
        user_id = message.from_user.id

    status_msg = await message.reply("⏳ MAKING AMERICA GREAT AGAIN...")

    output_path = f"temp_trump_tweet_{message.message_id}.png"
    avatar_path = f"temp_trump_avatar_{message.message_id}.jpg"

    processed_ok = False
    try:
        trumpified = await run_in_thread(ctx.groq.trumpify_text, original_text=original)
        await download_user_avatar(bot=bot, user_id=user_id, output_path=avatar_path)

        img_ok = await run_in_thread(
            create_trump_tweet_image,
            text=trumpified,
            output_path=output_path,
            avatar_path=avatar_path,
        )

        if img_ok:
            await message.answer_photo(
                FSInputFile(output_path),
                caption="🇺🇸 **TRUMP MODE ACTIVATED** 🇺🇸",
                parse_mode="Markdown",
            )
        else:
            await message.answer(f"🇺🇸 TRUMP MODE ACTIVATED 🇺🇸\n\n{trumpified}")

        processed_ok = True

    except Exception as e:
        logging.error("Trump command error: %s", e, exc_info=True)
        await message.answer("FAKE NEWS! Ошибка трампификации 🇺🇸")
    finally:
        try:
            await status_msg.delete()
        except Exception:
            pass

        for f in (output_path, avatar_path):
            try:
                if os.path.exists(f):
                    os.remove(f)
            except Exception:
                pass

        if processed_ok:
            try:
                await ctx.rating.add_points(user=message.from_user, delta=1)
            except Exception:
                pass

