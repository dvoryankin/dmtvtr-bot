from __future__ import annotations

from aiogram import Router

from handlers.debug import router as debug_router
from handlers.demotivator import router as demotivator_router
from handlers.emoji import router as emoji_router
from handlers.help import router as help_router
from handlers.rating import router as rating_router
from handlers.tenet import router as tenet_router
from handlers.trump import router as trump_router
from handlers.link_fix import router as link_fix_router
from handlers.get_notify import router as get_notify_router
from handlers.quiz import router as quiz_router
from handlers.minigame import router as minigame_router


def all_routers() -> list[Router]:
    # Order matters for some generic handlers (e.g. emoji naming text input).
    return [
        quiz_router,
        minigame_router,
        get_notify_router,
        emoji_router,
        debug_router,
        rating_router,
        tenet_router,
        trump_router,
        link_fix_router,
        help_router,
        demotivator_router,
    ]
