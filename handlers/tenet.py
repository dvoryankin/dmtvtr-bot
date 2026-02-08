from __future__ import annotations

import os
import logging

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

from app.context import AppContext
from utils.asyncio_utils import run_in_thread
from utils.server_load import check_server_load, send_overload_message
from utils.tenet import (
    calculate_antipode,
    mirror_image,
    reverse_audio,
    reverse_pdf,
    reverse_text,
    reverse_video,
)


router = Router(name="tenet")


@router.message(Command("tenet"))
async def cmd_tenet(message: Message, bot: Bot, ctx: AppContext) -> None:
    if not message.reply_to_message:
        await message.reply(
            "🔄 *Команда /tenet* — переворачивает всё!\n\n"
            "Ответь на сообщение:\n"
            "• 📝 Текст → текст наоборот\n"
            "• 🖼 Фото → зеркало\n"
            "• 🎬 Видео/GIF → задом наперёд\n"
            "• 🎤 Голосовое → реверс аудио\n"
            "• 🎵 Аудио → реверс\n"
            "• 📄 PDF → страницы в обратном порядке\n"
            "• 📍 Локация → антипод (противоположная точка Земли)",
            parse_mode="Markdown",
        )
        return

    replied = message.reply_to_message
    status_msg = await message.reply("⏳ Обрабатываем в стиле Тенет...")

    input_file = f"temp_tenet_in_{message.message_id}"
    output_file = f"temp_tenet_out_{message.message_id}"
    processed_ok = False

    try:
        # === LOCATION ===
        if replied.location:
            anti = calculate_antipode(lat=replied.location.latitude, lon=replied.location.longitude)
            await status_msg.edit_text(
                f"🌍 Исходная точка: {replied.location.latitude:.6f}, {replied.location.longitude:.6f}\n"
                f"🔄 Пробиваем Землю насквозь...\n"
                f"🌏 Антипод: {anti.lat:.6f}, {anti.lon:.6f}"
            )
            await message.answer_location(latitude=anti.lat, longitude=anti.lon)
            processed_ok = True
            return

        # === TEXT ===
        if replied.text:
            await status_msg.edit_text(f"🔄 {reverse_text(replied.text)}")
            processed_ok = True
            return

        # === PHOTO ===
        if replied.photo:
            input_file += ".jpg"
            output_file += ".jpg"
            await bot.download(replied.photo[-1], destination=input_file)
            await status_msg.edit_text("⏳ Зеркалим изображение...")
            success = await run_in_thread(mirror_image, img_path=input_file, output_path=output_file)
            if success:
                await message.answer_photo(FSInputFile(output_file))
                processed_ok = True
            else:
                await message.answer("Ошибка при зеркалировании")
            return

        # === VOICE ===
        if replied.voice:
            input_file += ".ogg"
            output_file += ".ogg"
            await bot.download(replied.voice, destination=input_file)
            await status_msg.edit_text("⏳ Переворачиваем голосовое...")
            success = await run_in_thread(reverse_audio, audio_path=input_file, output_path=output_file)
            if success:
                await message.answer_voice(FSInputFile(output_file))
                processed_ok = True
            else:
                await message.answer("Ошибка при реверсе голосового")
            return

        # === AUDIO ===
        if replied.audio:
            ext = ".mp3"
            if replied.audio.file_name:
                ext = os.path.splitext(replied.audio.file_name)[1] or ".mp3"
            input_file += ext
            output_file += ".ogg"
            await bot.download(replied.audio, destination=input_file)
            await status_msg.edit_text("⏳ Переворачиваем аудио...")
            success = await run_in_thread(reverse_audio, audio_path=input_file, output_path=output_file)
            if success:
                await message.answer_audio(FSInputFile(output_file), title="Reversed Audio")
                processed_ok = True
            else:
                await message.answer("Ошибка при реверсе аудио")
            return

        # === DOCUMENT ===
        if replied.document:
            mime = replied.document.mime_type or ""
            fname = replied.document.file_name or "file"

            if "pdf" in mime or fname.lower().endswith(".pdf"):
                input_file += ".pdf"
                output_file += ".pdf"
                await bot.download(replied.document, destination=input_file)
                await status_msg.edit_text("⏳ Переворачиваем страницы PDF...")
                success = await run_in_thread(reverse_pdf, pdf_path=input_file, output_path=output_file)
                if success:
                    await message.answer_document(FSInputFile(output_file, filename="reversed.pdf"))
                    processed_ok = True
                else:
                    await message.answer("Ошибка при реверсе PDF (нужен PyPDF2)")
                return

            if "image" in mime:
                input_file += ".jpg"
                output_file += ".jpg"
                await bot.download(replied.document, destination=input_file)
                await status_msg.edit_text("⏳ Зеркалим изображение...")
                success = await run_in_thread(mirror_image, img_path=input_file, output_path=output_file)
                if success:
                    await message.answer_photo(FSInputFile(output_file))
                    processed_ok = True
                else:
                    await message.answer("Ошибка при зеркалировании")
                return

            if "text" in mime or fname.endswith((".txt", ".md", ".json", ".xml", ".html", ".css", ".js", ".py")):
                input_file += ".txt"
                await bot.download(replied.document, destination=input_file)
                with open(input_file, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                reversed_content = reverse_text(content)
                if len(reversed_content) > 4000:
                    output_file += ".txt"
                    with open(output_file, "w", encoding="utf-8") as f:
                        f.write(reversed_content)
                    await message.answer_document(
                        FSInputFile(output_file, filename=f"reversed_{fname}")
                    )
                else:
                    await message.answer(f"```\n{reversed_content[:4000]}\n```", parse_mode="Markdown")
                processed_ok = True
                return

            if "video" in mime:
                can_process, count = check_server_load(
                    max_concurrent_processes=ctx.settings.max_concurrent_processes
                )
                if not can_process:
                    await send_overload_message(
                        message,
                        process_count=count,
                        max_concurrent_processes=ctx.settings.max_concurrent_processes,
                        light_image=ctx.settings.overload_image_light,
                        heavy_image=ctx.settings.overload_image_heavy,
                    )
                    return

                input_file += ".mp4"
                output_file += ".mp4"
                await bot.download(replied.document, destination=input_file)
                await status_msg.edit_text("⏳ Переворачиваем видео...")
                success = await run_in_thread(reverse_video, vid_path=input_file, output_path=output_file)
                if success:
                    await message.answer_video(FSInputFile(output_file))
                    processed_ok = True
                else:
                    await message.answer("Ошибка при реверсе видео")
                return

            await message.answer(f"Не знаю как перевернуть этот тип файла: {mime}")
            return

        # === VIDEO / ANIMATION / VIDEO NOTE ===
        if replied.video or replied.animation or replied.video_note:
            can_process, count = check_server_load(
                max_concurrent_processes=ctx.settings.max_concurrent_processes
            )
            if not can_process:
                await send_overload_message(
                    message,
                    process_count=count,
                    max_concurrent_processes=ctx.settings.max_concurrent_processes,
                    light_image=ctx.settings.overload_image_light,
                    heavy_image=ctx.settings.overload_image_heavy,
                )
                return

            obj = replied.video or replied.animation or replied.video_note
            input_file += ".mp4"
            output_file += ".mp4"
            await bot.download(obj, destination=input_file)
            await status_msg.edit_text("⏳ Переворачиваем время...")
            success = await run_in_thread(reverse_video, vid_path=input_file, output_path=output_file)
            if success:
                # For GIF/animation use answer_animation, for video answer_video.
                if replied.animation or replied.video_note:
                    await message.answer_animation(FSInputFile(output_file))
                else:
                    await message.answer_video(FSInputFile(output_file))
                processed_ok = True
            else:
                await message.answer("Ошибка при реверсе видео")
            return

        # === STICKER ===
        if replied.sticker:
            file_info = await bot.get_file(replied.sticker.file_id)
            file_path = file_info.file_path or ""

            if file_path.endswith(".webm"):
                can_process, count = check_server_load(
                    max_concurrent_processes=ctx.settings.max_concurrent_processes
                )
                if not can_process:
                    await send_overload_message(
                        message,
                        process_count=count,
                        max_concurrent_processes=ctx.settings.max_concurrent_processes,
                        light_image=ctx.settings.overload_image_light,
                        heavy_image=ctx.settings.overload_image_heavy,
                    )
                    return

                input_file += ".webm"
                output_file += ".mp4"
                await bot.download(replied.sticker, destination=input_file)
                await status_msg.edit_text("⏳ Переворачиваем видео-стикер...")
                success = await run_in_thread(reverse_video, vid_path=input_file, output_path=output_file)
                if success:
                    await message.answer_animation(FSInputFile(output_file))
                    processed_ok = True
                else:
                    await message.answer("Ошибка при реверсе стикера")
                return

            if file_path.endswith(".webp") or file_path.endswith(".png"):
                input_file += ".webp"
                output_file += ".jpg"
                await bot.download(replied.sticker, destination=input_file)
                await status_msg.edit_text("⏳ Зеркалим стикер...")
                success = await run_in_thread(mirror_image, img_path=input_file, output_path=output_file)
                if success:
                    await message.answer_photo(FSInputFile(output_file))
                    processed_ok = True
                else:
                    await message.answer("Ошибка при зеркалировании стикера")
                return

            if file_path.endswith(".tgs"):
                await message.answer("TGS стикеры пока не поддерживаются для /tenet")
                return

            await message.answer("Неизвестный тип стикера")
            return

        await message.answer("Не могу обработать этот тип сообщения")

    except Exception as e:
        logging.error("Tenet command error: %s", e, exc_info=True)
        await message.answer("Произошла ошибка при обработке")
    finally:
        try:
            await status_msg.delete()
        except Exception:
            pass

        for f in (input_file, output_file):
            try:
                if os.path.exists(f):
                    os.remove(f)
            except Exception:
                pass

        if processed_ok and message.from_user:
            try:
                await ctx.rating.add_points(user=message.from_user, delta=1)
            except Exception:
                # Rating must never break command flow.
                pass

