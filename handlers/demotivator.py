from __future__ import annotations

import glob
import logging
import os

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.types import FSInputFile, Message

from app.context import AppContext
from demotivator.image_creator import create_demotivator_image
from demotivator.layout import LayoutConfig
from demotivator.video_creator import create_demotivator_video
from utils.asyncio_utils import run_in_thread
from utils.fallback_media import get_random_fallback_image
from utils.media_converter import convert_tgs_to_mp4_simple
from utils.server_load import check_server_load, send_overload_message
from utils.text import generate_text_image


router = Router(name="demotivator")


def _layout_cfg(ctx: AppContext) -> LayoutConfig:
    return ctx.layout_cfg


async def _reject_if_overloaded(message: Message, ctx: AppContext) -> bool:
    can_process, count = check_server_load(max_concurrent_processes=ctx.settings.max_concurrent_processes)
    if can_process:
        return False
    logging.warning("Server overloaded (%s processes), rejecting request", count)
    await send_overload_message(
        message,
        process_count=count,
        max_concurrent_processes=ctx.settings.max_concurrent_processes,
        light_image=ctx.settings.overload_image_light,
        heavy_image=ctx.settings.overload_image_heavy,
    )
    return True


def _effect_for_command(cmd: str) -> str | None:
    cmd = cmd.lower()
    if cmd == "inv":
        return "invert"
    if cmd == "vin":
        return "vintage"
    return None


@router.message((F.photo | F.document) & F.caption)
async def handle_media_with_caption(message: Message, bot: Bot, ctx: AppContext) -> None:
    caption = (message.caption or "").strip()
    if not caption.startswith("/"):
        return

    # /emoji caption is handled in handlers/emoji.py
    cmd_prefixes = ("/d", "/dd", "/д", "/дд", "/inv", "/vin")
    if not any(caption.lower().startswith(p) for p in cmd_prefixes):
        return

    if await _reject_if_overloaded(message, ctx):
        return

    # Parse: "/cmd args..."
    parts = caption.split(maxsplit=1)
    cmd = parts[0].lstrip("/").split("@", 1)[0]
    effect = _effect_for_command(cmd)
    final_caption = parts[1] if len(parts) > 1 else "..."

    status_msg = await message.reply("⏳ Делаем демотиватор...")
    input_file = f"temp_in_{message.message_id}.jpg"
    output_file = f"temp_out_{message.message_id}.jpg"

    processed_ok = False
    try:
        if message.photo:
            await bot.download(message.photo[-1], destination=input_file)
        else:
            await bot.download(message.document, destination=input_file)

        success = await run_in_thread(
            create_demotivator_image,
            img_path=input_file,
            text=final_caption,
            output_path=output_file,
            layout_cfg=_layout_cfg(ctx),
            effect=effect,
        )
        if success:
            await message.answer_photo(FSInputFile(output_file))
            processed_ok = True
        else:
            await message.answer("Ошибка обработки")

    except Exception as e:
        logging.error("Media caption handler error: %s", e, exc_info=True)
        await message.answer("Произошла ошибка")
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
                pass


@router.message(Command("d", "dd", "д", "дд", "inv", "vin"))
async def handle_command(message: Message, bot: Bot, command: CommandObject, ctx: AppContext) -> None:
    if not message.from_user:
        return

    if await _reject_if_overloaded(message, ctx):
        return

    effect = _effect_for_command(command.command)
    args = (command.args or "").strip()

    # === NO REPLY: pick random sticker ===
    if not message.reply_to_message:
        if args:
            caption = args
        else:
            caption = await run_in_thread(ctx.groq.generate_demotivator_text)
            logging.info("Using AI-generated caption: %s", caption)

        status_msg = await message.reply("⏳ Выбираю стикер...")
        processed_ok = False

        try:
            fallback_file = await get_random_fallback_image(
                bot, message_id=message.message_id, fallback_avatar=ctx.settings.fallback_avatar
            )
            if not fallback_file:
                await message.answer("Не удалось получить стикер")
                return

            if fallback_file.endswith(".webm"):
                output_file = f"temp_out_{message.message_id}.mp4"
                success = await run_in_thread(
                    create_demotivator_video,
                    vid_path=fallback_file,
                    text=caption,
                    output_path=output_file,
                    layout_cfg=_layout_cfg(ctx),
                )
                if success:
                    await message.answer_animation(FSInputFile(output_file))
                    processed_ok = True
                else:
                    await message.answer("Ошибка обработки")
            else:
                output_file = f"temp_out_{message.message_id}.jpg"
                success = await run_in_thread(
                    create_demotivator_image,
                    img_path=fallback_file,
                    text=caption,
                    output_path=output_file,
                    layout_cfg=_layout_cfg(ctx),
                    is_avatar=True,
                    effect=effect,
                )
                if success:
                    await message.answer_photo(FSInputFile(output_file))
                    processed_ok = True
                else:
                    await message.answer("Ошибка обработки")

        except Exception as e:
            logging.error("Solo command error: %s", e, exc_info=True)
            await message.answer("Ошибка при получении стикера")
        finally:
            try:
                await status_msg.delete()
            except Exception:
                pass

            # Cleanup temp artifacts
            for pattern in (
                f"temp_fallback_{message.message_id}*",
                f"temp_in_{message.message_id}*",
                f"temp_out_{message.message_id}*",
                f"temp_text_{message.message_id}*",
                f"temp_trump_*_{message.message_id}*",
            ):
                for file_path in glob.glob(pattern):
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass

            if processed_ok:
                try:
                    await ctx.rating.add_points(user=message.from_user, delta=1)
                except Exception:
                    pass

        return

    # === REPLY MODE ===
    replied = message.reply_to_message
    final_caption = args if args else "..."

    status_msg = await message.reply("⏳ Делаем...")
    input_file_base = f"temp_in_{message.message_id}"
    output_file_jpg = f"temp_out_{message.message_id}.jpg"
    text_img_file = f"temp_text_{message.message_id}.jpg"

    processed_ok = False
    try:
        # Video notes
        if replied.video_note:
            input_file = input_file_base + ".mp4"
            output_file = f"temp_out_{message.message_id}.mp4"
            await bot.download(replied.video_note, destination=input_file)
            await status_msg.edit_text("⏳ Обрабатываем кружок...")
            success = await run_in_thread(
                create_demotivator_video,
                vid_path=input_file,
                text=final_caption,
                output_path=output_file,
                layout_cfg=_layout_cfg(ctx),
            )
            if success:
                await message.answer_animation(FSInputFile(output_file))
                processed_ok = True
            else:
                await message.answer("Ошибка обработки кружка")

        # Videos / GIFs
        elif replied.video or replied.animation:
            if effect:
                await message.answer("Эффекты работают только с изображениями")
                return

            input_file = input_file_base + ".mp4"
            output_file = f"temp_out_{message.message_id}.mp4"
            obj = replied.video if replied.video else replied.animation
            await bot.download(obj, destination=input_file)
            await status_msg.edit_text("⏳ Рендерим видео...")
            success = await run_in_thread(
                create_demotivator_video,
                vid_path=input_file,
                text=final_caption,
                output_path=output_file,
                layout_cfg=_layout_cfg(ctx),
            )
            if success:
                await message.answer_animation(FSInputFile(output_file))
                processed_ok = True
            else:
                await message.answer("Ошибка видео")

        # Images
        elif replied.photo or (
            replied.document and replied.document.mime_type and "image" in replied.document.mime_type
        ):
            obj = replied.photo[-1] if replied.photo else replied.document
            input_file = input_file_base + ".jpg"
            await bot.download(obj, destination=input_file)
            success = await run_in_thread(
                create_demotivator_image,
                img_path=input_file,
                text=final_caption,
                output_path=output_file_jpg,
                layout_cfg=_layout_cfg(ctx),
                effect=effect,
            )
            if success:
                await message.answer_photo(FSInputFile(output_file_jpg))
                processed_ok = True
            else:
                await message.answer("Ошибка фото")

        # Stickers
        elif replied.sticker:
            file_info = await bot.get_file(replied.sticker.file_id)
            file_path = file_info.file_path or ""

            # TGS stickers
            if file_path.endswith(".tgs"):
                input_file = input_file_base + ".tgs"
                await bot.download(replied.sticker, destination=input_file)
                video_file = input_file.replace(".tgs", "_anim.mp4")
                await status_msg.edit_text("⏳ Рендерим анимацию...")

                conv_ok = await run_in_thread(
                    convert_tgs_to_mp4_simple, tgs_path=input_file, output_mp4=video_file
                )
                if conv_ok:
                    output_file = f"temp_out_{message.message_id}.mp4"
                    vid_ok = await run_in_thread(
                        create_demotivator_video,
                        vid_path=video_file,
                        text=final_caption,
                        output_path=output_file,
                        layout_cfg=_layout_cfg(ctx),
                    )
                    if vid_ok:
                        await message.answer_animation(FSInputFile(output_file))
                        processed_ok = True
                    else:
                        await message.answer("Ошибка обработки")
                else:
                    if replied.sticker.thumbnail:
                        thumb_file = input_file_base + ".jpg"
                        await bot.download(replied.sticker.thumbnail, destination=thumb_file)
                        img_ok = await run_in_thread(
                            create_demotivator_image,
                            img_path=thumb_file,
                            text=final_caption,
                            output_path=output_file_jpg,
                            layout_cfg=_layout_cfg(ctx),
                            is_avatar=True,
                            effect=effect,
                        )
                        if img_ok:
                            await message.answer_photo(FSInputFile(output_file_jpg))
                            processed_ok = True

                for f in (video_file,):
                    try:
                        if os.path.exists(f):
                            os.remove(f)
                    except Exception:
                        pass

            # Video stickers (.webm)
            elif file_path.endswith(".webm"):
                if effect:
                    await message.answer("Эффекты работают только с изображениями")
                    return
                input_file = input_file_base + ".webm"
                output_file = f"temp_out_{message.message_id}.mp4"
                await bot.download(replied.sticker, destination=input_file)
                success = await run_in_thread(
                    create_demotivator_video,
                    vid_path=input_file,
                    text=final_caption,
                    output_path=output_file,
                    layout_cfg=_layout_cfg(ctx),
                )
                if success:
                    await message.answer_animation(FSInputFile(output_file))
                    processed_ok = True
                else:
                    await message.answer("Ошибка обработки видео стикера")

            # Static stickers
            else:
                input_file = input_file_base + ".webp"
                await bot.download(replied.sticker, destination=input_file)
                success = await run_in_thread(
                    create_demotivator_image,
                    img_path=input_file,
                    text=final_caption,
                    output_path=output_file_jpg,
                    layout_cfg=_layout_cfg(ctx),
                    is_avatar=True,
                    effect=effect,
                )
                if success:
                    await message.answer_photo(FSInputFile(output_file_jpg))
                    processed_ok = True

        # Text replies
        elif replied.text:
            text_content = replied.text.strip()
            avatar_file = None
            try:
                if replied.from_user:
                    photos = await bot.get_user_profile_photos(replied.from_user.id, limit=1)
                    if photos.total_count > 0:
                        avatar_file = input_file_base + ".jpg"
                        await bot.download(photos.photos[0][-1], destination=avatar_file)
            except Exception:
                avatar_file = None

            if not avatar_file:
                avatar_file = await get_random_fallback_image(
                    bot, message_id=message.message_id, fallback_avatar=ctx.settings.fallback_avatar
                )

            if avatar_file:
                text_for_demot = args if args else text_content
                success = await run_in_thread(
                    create_demotivator_image,
                    img_path=avatar_file,
                    text=text_for_demot,
                    output_path=output_file_jpg,
                    layout_cfg=_layout_cfg(ctx),
                    is_avatar=True,
                    effect=effect,
                )
                if success:
                    await message.answer_photo(FSInputFile(output_file_jpg))
                    processed_ok = True
            else:
                # Generate image from text.
                if await run_in_thread(
                    generate_text_image,
                    text=text_content,
                    output_path=text_img_file,
                    font_paths=ctx.settings.font_paths,
                    unicode_font_paths=ctx.settings.unicode_font_paths,
                ):
                    ok = await run_in_thread(
                        create_demotivator_image,
                        img_path=text_img_file,
                        text=final_caption,
                        output_path=output_file_jpg,
                        layout_cfg=_layout_cfg(ctx),
                        effect=effect,
                    )
                    if ok:
                        await message.answer_photo(FSInputFile(output_file_jpg))
                        processed_ok = True

        # Fallback: generate from text
        else:
            fallback_text = args if args else "Unknown"
            if await run_in_thread(
                generate_text_image,
                text=fallback_text,
                output_path=text_img_file,
                font_paths=ctx.settings.font_paths,
                unicode_font_paths=ctx.settings.unicode_font_paths,
            ):
                ok = await run_in_thread(
                    create_demotivator_image,
                    img_path=text_img_file,
                    text=fallback_text,
                    output_path=output_file_jpg,
                    layout_cfg=_layout_cfg(ctx),
                    effect=effect,
                )
                if ok:
                    await message.answer_photo(FSInputFile(output_file_jpg))
                    processed_ok = True

    except Exception as e:
        logging.error("Demotivator command error: %s", e, exc_info=True)
        await message.answer("Ошибка обработки")
    finally:
        try:
            await status_msg.delete()
        except Exception:
            pass

        for f in os.listdir("."):
            if (
                f.startswith(f"temp_in_{message.message_id}")
                or f.startswith(f"temp_out_{message.message_id}")
                or f.startswith(f"temp_text_{message.message_id}")
                or f.startswith(f"temp_fallback_{message.message_id}")
            ):
                try:
                    os.remove(f)
                except Exception:
                    pass

        if processed_ok:
            try:
                await ctx.rating.add_points(user=message.from_user, delta=1)
            except Exception:
                pass

