from __future__ import annotations

from aiogram import Router

from handlers.debug import router as debug_router
from handlers.demotivator import router as demotivator_router
from handlers.emoji import router as emoji_router
from handlers.help import router as help_router
from handlers.rating import router as rating_router
from handlers.tenet import router as tenet_router
from handlers.trump import router as trump_router


def all_routers() -> list[Router]:
    # Order matters for some generic handlers (e.g. emoji naming text input).
    return [
        emoji_router,
        debug_router,
        rating_router,
        tenet_router,
        trump_router,
        help_router,
        demotivator_router,
    ]
