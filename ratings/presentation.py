from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import Message

    from ratings.service import VoteResult


_EFFECT_STICKER_SET = "AnimatedEmojies"
_EFFECT_EMOJIS = frozenset({"💥", "🔥", "🎉", "⚡", "✨", "🤯", "🥳", "🎆", "🎇", "💫"})
_effect_sticker_ids: tuple[str, ...] | None = None


def compact_vote_text(*, result: VoteResult, display_name: str, badge: str) -> str:
    """Keep rating replies readable even when several random events trigger."""
    if result.ghost:
        return f"👻 {display_name}: без изменений"

    shown_delta = result.display_delta if result.display_delta is not None else result.delta
    delta = int(shown_delta or 0)
    sign = f"+{delta}" if delta >= 0 else str(delta)
    return f"{sign} {display_name} → {result.new_rating} · {badge}"


async def send_vote_effect_sticker(*, bot: Bot, message: Message) -> None:
    global _effect_sticker_ids

    try:
        if _effect_sticker_ids is None:
            sticker_set = await bot.get_sticker_set(_EFFECT_STICKER_SET)
            _effect_sticker_ids = tuple(
                sticker.file_id
                for sticker in sticker_set.stickers
                if sticker.emoji in _EFFECT_EMOJIS and (sticker.is_animated or sticker.is_video)
            )

        if _effect_sticker_ids:
            await message.answer_sticker(random.choice(_effect_sticker_ids))
    except Exception:
        logging.exception("Failed to send rating effect sticker")
