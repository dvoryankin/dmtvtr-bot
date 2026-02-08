from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time

from aiogram import Bot, F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputSticker,
    Message,
)
from PIL import Image

from app.context import AppContext
from utils.asyncio_utils import run_in_thread
from utils.emoji_pack import (
    calculate_grid_size,
    create_custom_emoji_pack,
    split_image_to_grid,
    split_video_to_grid,
)


router = Router(name="emoji")

# Pending state: stores temp_dir, input_file, is_video, etc.
emoji_pack_pending: dict[str, dict] = {}
emoji_pack_naming: dict[str, dict] = {}


async def _create_emoji_pack_with_name(
    *,
    message: Message,
    bot: Bot,
    ctx: AppContext,
    user_id: int,
    data: dict,
    pack_title: str,
) -> None:
    """Create emoji pack with progress + user-provided title."""
    input_file: str = data["input_file"]
    is_video: bool = data["is_video"]
    temp_dir: str = data["temp_dir"]
    cols: int = data["cols"]
    rows: int = data["rows"]

    status_msg = await message.answer(
        f"🔪 **Режу картинку на {cols}×{rows}...**\n"
        f"📝 Название: **{pack_title}**\n\n"
        f"⏳ Прогресс: 0%",
        parse_mode="Markdown",
    )

    try:
        # === SPLIT ===
        if is_video:
            output_parts = await run_in_thread(
                split_video_to_grid, video_path=input_file, cols=cols, rows=rows, output_dir=temp_dir
            )
        else:
            output_parts = await run_in_thread(
                split_image_to_grid, image_path=input_file, cols=cols, rows=rows, output_dir=temp_dir
            )

        if not output_parts:
            await status_msg.edit_text("❌ Ошибка при нарезке медиа")
            return

        await status_msg.edit_text(
            f"🔪 **Режу картинку на {cols}×{rows}...**\n"
            f"📝 Название: **{pack_title}**\n\n"
            f"⏳ Прогресс: 50%",
            parse_mode="Markdown",
        )

        # === CREATE STICKER SET ===
        timestamp = int(time.time())
        bot_info = await bot.me()
        bot_username = bot_info.username
        pack_name = f"img_{user_id}_{timestamp}_by_{bot_username}"

        await status_msg.edit_text(
            f"🔪 **Режу картинку на {cols}×{rows}...**\n"
            f"📝 Название: **{pack_title}**\n\n"
            f"⏳ Прогресс: 75%",
            parse_mode="Markdown",
        )

        # Spacers to keep rows aligned in Telegram UI (8 per row).
        telegram_row_width = 8
        padding_count = max(0, telegram_row_width - cols)

        spacer_webp = f"{temp_dir}/spacer.webp"
        spacer_img = Image.new("RGBA", (1, 100), (255, 255, 255, 1))
        spacer_img.save(spacer_webp, "WEBP", quality=95)
        with open(spacer_webp, "rb") as f:
            spacer_data = f.read()

        stickers: list[InputSticker] = []
        emoji_map = [
            "🟦",
            "🟩",
            "🟥",
            "🟧",
            "🟨",
            "🟪",
            "⬜",
            "⬛",
            "🔵",
            "🟫",
            "🔴",
            "🟢",
            "🟡",
            "🟣",
            "🟤",
            "⚫",
            "⚪",
            "🔶",
            "🔷",
            "🔸",
        ]

        for row_idx in range(rows):
            for col_idx in range(cols):
                i = row_idx * cols + col_idx
                if i >= len(output_parts):
                    break

                part_path = output_parts[i]
                with open(part_path, "rb") as f:
                    file_data = f.read()

                filename = f"part_{i}.webm" if is_video else f"part_{i}.webp"
                stickers.append(
                    InputSticker(
                        sticker=BufferedInputFile(file_data, filename=filename),
                        emoji_list=[emoji_map[i % len(emoji_map)]],
                        format="video" if is_video else "static",
                    )
                )

            for pad_idx in range(padding_count):
                stickers.append(
                    InputSticker(
                        sticker=BufferedInputFile(spacer_data, filename=f"spacer_{row_idx}_{pad_idx}.webp"),
                        emoji_list=["⬜"],
                        format="static",
                    )
                )

        if not stickers:
            await status_msg.edit_text("❌ Не удалось подготовить стикеры")
            return

        result = await bot.create_new_sticker_set(
            user_id=user_id,
            name=pack_name,
            title=pack_title,
            stickers=stickers,
            sticker_type="custom_emoji",
        )
        if not result:
            await status_msg.edit_text("❌ Не удалось создать стикер-пак")
            return

        pack_link = f"https://t.me/addemoji/{pack_name}"
        await status_msg.edit_text(
            "🎉 **Готово! Эмодзи-пак создан!**\n\n"
            f"🔗 **Ссылка:** {pack_link}\n\n"
            "Нажмите на ссылку чтобы добавить эмодзи-пак и использовать их в своих сообщениях.\n",
            parse_mode="Markdown",
            disable_web_page_preview=False,
        )

        if message.from_user:
            try:
                await ctx.rating.add_points(user=message.from_user, delta=3)
            except Exception:
                pass

    except Exception as e:
        error_msg = str(e)
        logging.error("Failed to create emoji pack: %s", error_msg, exc_info=True)
        if "STICKERSET_INVALID" in error_msg:
            await message.answer("❌ Ошибка создания пака. Попробуйте уменьшить размер сетки.")
        elif "name is already" in error_msg.lower():
            await message.answer("❌ Пак с таким именем уже существует. Попробуйте ещё раз.")
        else:
            await message.answer(f"❌ Ошибка создания пака: {error_msg[:100]}")
    finally:
        try:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
        except Exception:
            pass


async def _process_emoji_pack(
    *,
    message: Message,
    bot: Bot,
    ctx: AppContext,
    user_id: int,
    input_file: str,
    is_video: bool,
    cols: int,
    rows: int,
    temp_dir: str,
) -> bool:
    total_emojis = cols * rows
    if total_emojis > 50:
        await message.answer(
            f"❌ Слишком большая сетка: {cols}x{rows} = {total_emojis} эмодзи\nМаксимум 50 эмодзи в паке"
        )
        return False

    status_msg = await message.answer(f"⏳ Нарезаю на сетку {cols}x{rows} ({total_emojis} эмодзи)...")
    try:
        if is_video:
            await status_msg.edit_text("⏳ Обрабатываю видео (может занять время)...")
            output_parts = await run_in_thread(
                split_video_to_grid, video_path=input_file, cols=cols, rows=rows, output_dir=temp_dir
            )
        else:
            output_parts = await run_in_thread(
                split_image_to_grid, image_path=input_file, cols=cols, rows=rows, output_dir=temp_dir
            )

        if not output_parts:
            await status_msg.edit_text("❌ Ошибка при нарезке медиа")
            return False

        await status_msg.edit_text(f"⏳ Создаю стикер-пак ({len(output_parts)} эмодзи)...")
        pack_name = await create_custom_emoji_pack(bot=bot, user_id=user_id, parts=output_parts, is_video=is_video)
        pack_link = f"https://t.me/addemoji/{pack_name}"
        await status_msg.edit_text(
            "✅ **Эмодзи-пак создан!**\n\n"
            f"🎨 Сетка: {cols}x{rows}\n"
            f"📦 Эмодзи: {len(output_parts)}\n"
            f"🎬 Тип: {'Анимированные' if is_video else 'Статичные'}\n\n"
            f"🔗 [Добавить пак]({pack_link})\n",
            parse_mode="Markdown",
            disable_web_page_preview=False,
        )

        if message.from_user:
            try:
                await ctx.rating.add_points(user=message.from_user, delta=2)
            except Exception:
                pass

        return True

    except Exception as e:
        error_msg = str(e)
        logging.error("Failed to create emoji pack: %s", error_msg, exc_info=True)
        await message.answer(f"❌ Ошибка создания пака: {error_msg[:100]}")
        return False
    finally:
        try:
            await status_msg.delete()
        except Exception:
            pass


@router.callback_query(F.data.startswith("emoji_grid:"))
async def emoji_grid_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        await callback.message.edit_text("❌ Ошибка обработки")
        return

    _prefix, user_id_str, cols_str, rows_str = parts
    user_id = int(user_id_str)
    cols = int(cols_str)
    rows = int(rows_str)

    if callback.from_user.id != user_id:
        await callback.answer("❌ Это не ваше сообщение", show_alert=True)
        return

    key = f"{user_id}_{callback.message.message_id}"
    if key not in emoji_pack_pending:
        await callback.message.edit_text("❌ Данные устарели. Отправьте картинку заново.")
        return

    data = emoji_pack_pending[key]
    data["cols"] = cols
    data["rows"] = rows

    keyboard = [
        [
            InlineKeyboardButton(
                text="Стандартное название",
                callback_data=f"emoji_name:default:{user_id}",
            )
        ]
    ]
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

    await callback.message.edit_text(
        f"✅ **Выбрана сетка:** {cols}×{rows}\n\n"
        f"📝 **Введите название пака** (до 15 символов):\n\n"
        f"Или нажмите кнопку для стандартного названия с размером сетки — **{cols}×{rows}**\n",
        parse_mode="Markdown",
        reply_markup=markup,
    )

    emoji_pack_naming[str(user_id)] = {"message_id": callback.message.message_id, "pending_key": key}


@router.callback_query(F.data.startswith("emoji_name:"))
async def emoji_name_callback(callback: CallbackQuery, bot: Bot, ctx: AppContext) -> None:
    await callback.answer()
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        return

    _prefix, _name_type, user_id_str = parts
    user_id = int(user_id_str)
    if callback.from_user.id != user_id:
        await callback.answer("❌ Это не ваше сообщение", show_alert=True)
        return

    naming_key = str(user_id)
    naming_data = emoji_pack_naming.get(naming_key)
    if not naming_data:
        await callback.message.edit_text("❌ Данные устарели.")
        return

    pending_key = naming_data["pending_key"]
    data = emoji_pack_pending.get(pending_key)
    if not data:
        await callback.message.edit_text("❌ Данные устарели.")
        emoji_pack_naming.pop(naming_key, None)
        return

    cols = data["cols"]
    rows = data["rows"]
    pack_title = f"{cols}x{rows}"

    await _create_emoji_pack_with_name(
        message=callback.message,
        bot=bot,
        ctx=ctx,
        user_id=user_id,
        data=data,
        pack_title=pack_title,
    )

    emoji_pack_naming.pop(naming_key, None)
    emoji_pack_pending.pop(pending_key, None)


@router.message(F.text)
async def emoji_pack_name_input(message: Message, bot: Bot, ctx: AppContext) -> None:
    if not message.from_user:
        raise SkipHandler

    naming_key = str(message.from_user.id)
    naming_data = emoji_pack_naming.get(naming_key)
    if not naming_data:
        raise SkipHandler

    pending_key = naming_data["pending_key"]
    data = emoji_pack_pending.get(pending_key)
    if not data:
        await message.answer("❌ Данные устарели. Отправьте картинку заново.")
        emoji_pack_naming.pop(naming_key, None)
        raise SkipHandler

    pack_title = (message.text or "").strip()[:15]
    if not pack_title:
        await message.answer("❌ Название не может быть пустым. Попробуйте ещё раз.")
        return

    await _create_emoji_pack_with_name(
        message=message,
        bot=bot,
        ctx=ctx,
        user_id=message.from_user.id,
        data=data,
        pack_title=pack_title,
    )

    emoji_pack_naming.pop(naming_key, None)
    emoji_pack_pending.pop(pending_key, None)


@router.message(Command("emoji"))
async def cmd_emoji(message: Message, bot: Bot, ctx: AppContext) -> None:
    # Parse optional grid size from text or caption.
    raw = message.text or message.caption or ""
    parts = raw.split()
    user_grid = parts[1] if len(parts) > 1 else None

    source = message.reply_to_message or message
    if source is message and not (
        message.photo or message.document or message.video or message.animation or message.sticker
    ):
        await message.reply(
            "🎨 **Команда /emoji** — создать эмодзи-пак из картинки/видео\n\n"
            "**Использование:**\n"
            "1️⃣ Ответь на фото/видео/GIF командой /emoji\n"
            "2️⃣ Или отправь медиа с подписью /emoji\n\n"
            "**Опции:**\n"
            "• /emoji — автоматический выбор сетки\n"
            "• /emoji 4x4 — сетка 4x4 (16 эмодзи)\n"
            "• /emoji 5x5 — сетка 5x5 (25 эмодзи)\n\n"
            "**Лимиты:**\n"
            "• Видео/GIF: до 3 секунд, до 10 МБ\n"
            "• Максимум 50 эмодзи в паке",
            parse_mode="Markdown",
        )
        return

    replied = source
    status_msg = await message.reply("⏳ Создаю эмодзи-пак...")

    temp_dir = tempfile.mkdtemp(prefix="emoji_pack_")
    input_file: str | None = None

    try:
        is_video = False
        is_image = False

        if replied.photo:
            is_image = True
            input_file = f"{temp_dir}/input.jpg"
            await bot.download(replied.photo[-1], destination=input_file)

        elif replied.document:
            mime = replied.document.mime_type or ""
            if "image" in mime:
                is_image = True
                ext = ".jpg"
                if "png" in mime:
                    ext = ".png"
                elif "webp" in mime:
                    ext = ".webp"
                input_file = f"{temp_dir}/input{ext}"
                await bot.download(replied.document, destination=input_file)
            elif "video" in mime or "gif" in mime:
                is_video = True
                input_file = f"{temp_dir}/input.mp4"
                await bot.download(replied.document, destination=input_file)
            else:
                await status_msg.edit_text("❌ Неподдерживаемый тип файла")
                return

        elif replied.video or replied.animation:
            is_video = True
            input_file = f"{temp_dir}/input.mp4"
            obj = replied.video if replied.video else replied.animation
            await bot.download(obj, destination=input_file)

        elif replied.sticker:
            file_info = await bot.get_file(replied.sticker.file_id)
            file_path = file_info.file_path or ""
            if file_path.endswith(".webm"):
                is_video = True
                input_file = f"{temp_dir}/input.webm"
                await bot.download(replied.sticker, destination=input_file)
            elif file_path.endswith(".webp") or file_path.endswith(".png"):
                is_image = True
                input_file = f"{temp_dir}/input.webp"
                await bot.download(replied.sticker, destination=input_file)
            elif file_path.endswith(".tgs"):
                await status_msg.edit_text(
                    "❌ TGS стикеры пока не поддерживаются.\nИспользуйте статичные стикеры или видео."
                )
                return
            else:
                await status_msg.edit_text("❌ Неизвестный тип стикера")
                return

        else:
            await status_msg.edit_text("❌ Отправь фото, видео, GIF или стикер")
            return

        # Determine width/height for recommendations.
        if not input_file:
            await status_msg.edit_text("❌ Не удалось подготовить входной файл")
            return

        if is_image:
            img = Image.open(input_file)
            width, height = img.size
            duration = 0.0
        else:
            # Probe video dims
            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=p=0",
                input_file,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                await status_msg.edit_text("❌ Ошибка обработки видео")
                return
            try:
                width, height = map(int, result.stdout.strip().split(","))
            except Exception:
                await status_msg.edit_text("❌ Не удалось определить размеры видео")
                return

            cmd_duration = [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                input_file,
            ]
            result_duration = subprocess.run(cmd_duration, capture_output=True, text=True, check=False)
            try:
                duration = float(result_duration.stdout.strip())
            except Exception:
                duration = 0.0

        is_private_chat = message.chat.type == "private"
        if is_private_chat and not user_grid:
            await status_msg.delete()

            grid_options = [
                (5, 3),
                (5, 4),
                (5, 5),
                (5, 6),
                (5, 8),
                (10, 5),
            ]
            grid_options = [(c, r) for c, r in grid_options if c * r <= 50]

            keyboard: list[list[InlineKeyboardButton]] = []
            for cols, rows in grid_options:
                total = cols * rows
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            text=f"{cols}×{rows} ({total} эмодзи)",
                            callback_data=f"emoji_grid:{message.from_user.id}:{cols}:{rows}",
                        )
                    ]
                )
            markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

            key = f"{message.from_user.id}_{message.message_id}"
            emoji_pack_pending[key] = {
                "input_file": input_file,
                "is_video": is_video,
                "temp_dir": temp_dir,
                "width": width,
                "height": height,
            }

            media_type = "Видео" if is_video else "Картинка"
            media_icon = "🎬" if is_video else "🖼️"
            duration_text = f"\n⏱️ Длительность: {duration:.1f} сек" if is_video and duration > 0 else ""

            await message.answer(
                f"✅ **{media_type} получен{'' if is_video else 'а'}!**\n"
                f"📐 Размер: {width}×{height} пикселей{duration_text}\n\n"
                f"{media_icon} **Выберите размер сетки{'для анимированных эмодзи' if is_video else ''}.**\n\n"
                "Рекомендую размер до 30-40 эмодзи.\n",
                reply_markup=markup,
                parse_mode="Markdown",
            )

            # Keep temp_dir until callback finishes.
            return

        cols, rows = calculate_grid_size(width, height, user_grid)
        await status_msg.delete()
        await _process_emoji_pack(
            message=message,
            bot=bot,
            ctx=ctx,
            user_id=message.from_user.id,
            input_file=input_file,
            is_video=is_video,
            cols=cols,
            rows=rows,
            temp_dir=temp_dir,
        )

    except Exception as e:
        logging.error("Emoji pack creation error: %s", e, exc_info=True)
        await message.answer(f"❌ Произошла ошибка: {str(e)[:100]}")
    finally:
        # Cleanup only if we are not waiting for callback.
        key = f"{message.from_user.id}_{message.message_id}" if message.from_user else ""
        if key and key in emoji_pack_pending:
            return
        try:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
        except Exception:
            pass


@router.message((F.photo | F.video | F.animation | F.document) & F.caption.startswith("/emoji"))
async def emoji_caption(message: Message, bot: Bot, ctx: AppContext) -> None:
    # Reuse the main command implementation for media-with-caption.
    await cmd_emoji(message, bot, ctx)
