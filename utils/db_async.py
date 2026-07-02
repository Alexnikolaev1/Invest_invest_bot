"""Асинхронная обёртка для синхронных вызовов SQLite без блокировки event loop."""

import asyncio
from functools import partial
from typing import Any, Callable, TypeVar

T = TypeVar("T")


async def run_db(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Выполняет синхронную функцию БД в thread pool executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))
