from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from services.aquastar_service import AquaStarError, get_current_load


router = Router(name="aquastar")


@router.message(Command("aquastar", "аквастар", "зал"))
async def cmd_aquastar(message: Message) -> None:
    try:
        load = await get_current_load()
    except AquaStarError as exc:
        logging.warning("AquaStar API request failed: %s", exc)
        await message.answer("Не удалось получить загруженность AquaStar. Попробуй позже.")
        return

    await message.answer(
        f"🏊 AQUASTAR Павелецкая: сейчас {load.people} посетителей."
    )
