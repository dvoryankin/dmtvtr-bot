from __future__ import annotations

import logging
import os
import subprocess
import time

from aiogram import Bot
from PIL import Image


def calculate_grid_size(width: int, height: int, user_grid: str | None = None) -> tuple[int, int]:
    """Pick a grid size based on aspect ratio or user-specified "<cols>x<rows>"."""
    if user_grid and "x" in user_grid.lower():
        try:
            parts = user_grid.lower().replace(" ", "").split("x")
            cols, rows = int(parts[0]), int(parts[1])
            if 2 <= cols <= 10 and 2 <= rows <= 10 and cols * rows <= 50:
                logging.info("Using user-specified grid: %sx%s", cols, rows)
                return cols, rows
        except Exception as e:
            logging.warning("Failed to parse user grid %r: %s", user_grid, e)

    aspect_ratio = width / height
    if 0.9 <= aspect_ratio <= 1.1:
        grid = (5, 5) if width >= 500 else (4, 4)
    elif aspect_ratio > 1.5:
        grid = (6, 4) if width >= 600 else (5, 3)
    elif aspect_ratio < 0.67:
        grid = (4, 6) if height >= 600 else (3, 5)
    else:
        grid = (4, 4)

    logging.info(
        "Auto-selected grid %sx%s for %sx%s (aspect %.2f)",
        grid[0],
        grid[1],
        width,
        height,
        aspect_ratio,
    )
    return grid


def split_image_to_grid(*, image_path: str, cols: int, rows: int, output_dir: str) -> list[str]:
    """Split an image into a grid and save WEBP parts (100x100)."""
    try:
        img = Image.open(image_path).convert("RGBA")
        width, height = img.size

        cell_width = width // cols
        cell_height = height // rows

        parts: list[str] = []
        for row in range(rows):
            for col in range(cols):
                left = col * cell_width
                top = row * cell_height
                right = left + cell_width
                bottom = top + cell_height

                cell = img.crop((left, top, right, bottom))
                cell = cell.resize((100, 100), Image.Resampling.LANCZOS)

                part_path = f"{output_dir}/part_{row}_{col}.webp"
                cell.save(part_path, "WEBP", quality=95)
                parts.append(part_path)

        logging.info("Split image into %s parts (%sx%s)", len(parts), cols, rows)
        return parts
    except Exception as e:
        logging.error("Error splitting image: %s", e, exc_info=True)
        return []


def _probe_video_dims(video_path: str) -> tuple[int, int] | None:
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
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        logging.error("ffprobe failed: %s", result.stderr)
        return None
    try:
        width, height = map(int, result.stdout.strip().split(","))
        return width, height
    except Exception:
        logging.error("Failed to parse video dimensions: %r", result.stdout)
        return None


def split_video_to_grid(*, video_path: str, cols: int, rows: int, output_dir: str) -> list[str]:
    """Split a video into WEBM parts (VP9) using ffmpeg crop+scale."""
    try:
        dims = _probe_video_dims(video_path)
        if dims is None:
            return []
        width, height = dims
        logging.info("Video dimensions: %sx%s", width, height)

        cell_width = width // cols
        cell_height = height // rows

        parts: list[str] = []
        for row in range(rows):
            for col in range(cols):
                x = col * cell_width
                y = row * cell_height
                output_path = f"{output_dir}/part_{row}_{col}.webm"

                cmd = [
                    "ffmpeg",
                    "-y",
                    "-i",
                    video_path,
                    "-t",
                    "3",
                    "-vf",
                    f"crop={cell_width}:{cell_height}:{x}:{y},scale=100:100",
                    "-c:v",
                    "libvpx-vp9",
                    "-b:v",
                    "150k",
                    "-an",
                    "-pix_fmt",
                    "yuva420p",
                    "-auto-alt-ref",
                    "0",
                    output_path,
                ]

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
                if result.returncode == 0 and os.path.exists(output_path):
                    file_size = os.path.getsize(output_path)
                    if file_size > 256 * 1024:
                        logging.warning("Part %s,%s is too large: %s bytes", row, col, file_size)
                    parts.append(output_path)
                else:
                    logging.error("Failed to create video part %s,%s: %s", row, col, result.stderr)

        logging.info("Split video into %s parts (%sx%s)", len(parts), cols, rows)
        return parts

    except subprocess.TimeoutExpired:
        logging.error("Video splitting timeout")
        return []
    except Exception as e:
        logging.error("Error splitting video: %s", e, exc_info=True)
        return []


async def create_custom_emoji_pack(
    *,
    bot: Bot,
    user_id: int,
    parts: list[str],
    is_video: bool = False,
) -> str:
    """Create a custom-emoji sticker set from parts and return pack name."""
    from aiogram.types import BufferedInputFile, InputSticker

    timestamp = int(time.time())
    bot_info = await bot.me()
    bot_username = bot_info.username

    pack_name = f"emoji_{user_id}_{timestamp}_by_{bot_username}"
    pack_title = f"Emoji Pack {timestamp}"

    logging.info("Creating custom emoji pack: %s (%s parts)", pack_name, len(parts))

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

    for i, part_path in enumerate(parts):
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

    result = await bot.create_new_sticker_set(
        user_id=user_id,
        name=pack_name,
        title=pack_title,
        stickers=stickers,
        sticker_type="custom_emoji",
    )
    if not result:
        raise RuntimeError("create_new_sticker_set returned False")
    return pack_name

