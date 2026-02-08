from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware

from app.context import AppContext


class ContextMiddleware(BaseMiddleware):
    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        data["ctx"] = self._ctx
        return await handler(event, data)

