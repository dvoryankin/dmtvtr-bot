from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.context import AppContext
from services.aquastar_service import AquaStarError, get_current_load


router = Router(name="aquastar")

_RATE_LIMIT_REQUESTS = 3
_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_BAN_SECONDS = 10 * 60
_RATE_LIMIT_EXEMPT_USERNAMES = {"pchellovod"}
_request_history: dict[int, list[float]] = {}
_bans: dict[int, float] = {}
_MOSCOW_TZ = timezone(timedelta(hours=3))
_STATS_COMMAND_RE = re.compile(r"^/(?:aquas|зал)(\d*)(?:@\w+)?$", re.IGNORECASE)


def _rate_limit_remaining(user_id: int, *, now: float | None = None) -> int:
    current_time = time.monotonic() if now is None else now
    ban_until = _bans.get(user_id)
    if ban_until is not None:
        if current_time < ban_until:
            return max(1, int(ban_until - current_time))
        _bans.pop(user_id, None)

    cutoff = current_time - _RATE_LIMIT_WINDOW_SECONDS
    recent = [timestamp for timestamp in _request_history.get(user_id, []) if timestamp > cutoff]
    if len(recent) >= _RATE_LIMIT_REQUESTS:
        _request_history.pop(user_id, None)
        _bans[user_id] = current_time + _RATE_LIMIT_BAN_SECONDS
        return _RATE_LIMIT_BAN_SECONDS

    recent.append(current_time)
    _request_history[user_id] = recent
    return 0


@router.message(Command("aquastar", "аквастар"))
async def cmd_aquastar(message: Message) -> None:
    username = (message.from_user.username or "").lower() if message.from_user is not None else ""
    if message.from_user is not None and username not in _RATE_LIMIT_EXEMPT_USERNAMES:
        remaining = _rate_limit_remaining(message.from_user.id)
        if remaining:
            await message.answer(
                f"Слишком много запросов к AquaStar. Бан на эту команду ещё {remaining} сек."
            )
            return

    try:
        load = await get_current_load()
    except AquaStarError as exc:
        logging.warning("AquaStar API request failed: %s", exc)
        await message.answer("Не удалось получить загруженность AquaStar. Попробуй позже.")
        return

    await message.answer(
        f"🏊 AQUASTAR Павелецкая: сейчас {load.people} посетителей."
    )


@router.message(F.text.regexp(_STATS_COMMAND_RE))
async def cmd_aquastar_stats(message: Message, ctx: AppContext) -> None:
    match = _STATS_COMMAND_RE.fullmatch(message.text or "")
    if match is None:
        return

    days = int(match.group(1) or "1")
    if not 1 <= days <= 365:
        await message.answer("Укажи период от 1 до 365 дней. Например: /aquas7 или /зал30")
        return

    period_label = f"{days} дн."
    period_seconds = days * 24 * 60 * 60
    summary = await ctx.aquastar_stats.summary(period_seconds=period_seconds)
    if summary is None:
        await message.answer(
            f"📊 AQUASTAR Павелецкая за {period_label}: пока нет замеров. "
            "Бот собирает их каждые 30 минут."
        )
        return

    def format_sample(ts: int, people: int) -> str:
        dt = datetime.fromtimestamp(ts, tz=_MOSCOW_TZ)
        return f"{people} чел. ({dt:%d.%m %H:%M})"

    quietest_hours = ", ".join(
        f"{item.hour:02d}:00 — {item.average_people:.1f}"
        for item in summary.quietest_hours
    )
    lowest_samples = ", ".join(
        format_sample(sample.ts, sample.people)
        for sample in sorted(summary.samples, key=lambda sample: (sample.people, sample.ts))[:3]
    )
    await message.answer(
        "\n".join(
            [
                f"📊 AQUASTAR Павелецкая за {period_label}",
                f"Замеров: {len(summary.samples)}",
                f"Среднее: {summary.average_people:.1f} чел.",
                f"Минимум: {format_sample(summary.min_sample.ts, summary.min_sample.people)}",
                f"Максимум: {format_sample(summary.max_sample.ts, summary.max_sample.people)}",
                f"Самые свободные часы (МСК, среднее): {quietest_hours}",
                f"Самые низкие замеры: {lowest_samples}",
            ]
        )
    )
