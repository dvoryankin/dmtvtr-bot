from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar


T = TypeVar("T")


async def run_in_thread(func: Callable[..., T], *args, **kwargs) -> T:
    """Run a blocking callable in a thread (compatible with older Python)."""
    try:
        to_thread = asyncio.to_thread  # Python 3.9+
    except AttributeError:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))
    return await to_thread(func, *args, **kwargs)
