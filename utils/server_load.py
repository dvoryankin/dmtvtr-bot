from __future__ import annotations

from pathlib import Path
import logging
import os
import subprocess

from aiogram.types import FSInputFile, Message


def check_server_load(*, max_concurrent_processes: int) -> tuple[bool, int]:
    """Count running ffmpeg processes and decide whether we can process more."""
    try:
        result = subprocess.run(
            ["pgrep", "-c", "ffmpeg"], capture_output=True, text=True, check=False
        )
        count = int(result.stdout.strip()) if result.returncode == 0 else 0
        can_process = count < max_concurrent_processes

        logging.info(
            "Load check: %s processes, limit %s, can_process=%s",
            count,
            max_concurrent_processes,
            can_process,
        )
        return can_process, count
    except Exception as e:
        logging.warning("Failed to check load: %s", e, exc_info=True)
        return True, 0


async def send_overload_message(
    message: Message,
    *,
    process_count: int,
    max_concurrent_processes: int,
    light_image: Path,
    heavy_image: Path,
) -> None:
    """Send an overload message with an optional image."""
    try:
        if process_count <= max_concurrent_processes + 1:
            image_path = light_image
            caption = (
                f"⚠️ Сервер загружен ({process_count} процессов)\n"
                f"Попробуй через секунду"
            )
        else:
            image_path = heavy_image
            caption = (
                f"⚠️ Сервер перегружен ({process_count} процессов)\n"
                f"Подожди немного"
            )

        if image_path.exists():
            await message.answer_photo(FSInputFile(str(image_path)), caption=caption)
        else:
            logging.error("Overload image not found: %s (cwd=%s)", image_path, os.getcwd())
            await message.answer(f"⚠️ Сервер перегружен ({process_count} процессов)")
    except Exception as e:
        logging.error("Failed to send overload message: %s", e, exc_info=True)
        await message.answer("⚠️ Слишком много запросов")

