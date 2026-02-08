from __future__ import annotations

import asyncio
from pathlib import Path
import logging

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher

from app.context import AppContext
from app.middleware import ActivityRatingMiddleware, ContextMiddleware
from config.config import Settings
from demotivator.layout import LayoutConfig
from handlers import all_routers
from ratings.service import RatingService
from services.groq_service import GroqService
from utils.logging_setup import configure_logging
from utils.temp_files import cleanup_old_temp_files


async def main() -> None:
    load_dotenv()

    base_dir = Path(__file__).resolve().parent
    settings = Settings.from_env(base_dir=base_dir)
    configure_logging(log_file=settings.log_file)

    if not settings.token:
        raise RuntimeError("BOT_TOKEN is not set (check .env)")

    rating = RatingService(
        db_path=settings.rating_db_path,
        vote_cooldown_seconds=settings.vote_cooldown_seconds,
        activity_points_per_award=settings.activity_points_per_award,
        activity_cooldown_seconds=settings.activity_cooldown_seconds,
    )
    rating.init_db()

    ctx = AppContext(
        settings=settings,
        layout_cfg=LayoutConfig(
            font_paths=settings.font_paths,
            unicode_font_paths=settings.unicode_font_paths,
        ),
        groq=GroqService(api_key=settings.groq_api_key),
        rating=rating,
    )

    bot = Bot(token=settings.token)
    dp = Dispatcher()
    dp.update.middleware(ContextMiddleware(ctx=ctx))
    # Activity and reply-based rating should run for *all* messages, even when no handler matches.
    dp.message.outer_middleware(ActivityRatingMiddleware(ctx=ctx))

    for r in all_routers():
        dp.include_router(r)

    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Bot started")
    cleanup_old_temp_files()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
