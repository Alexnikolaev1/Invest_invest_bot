"""Middleware для автоматической регистрации пользователей при любом взаимодействии."""

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from database import get_or_create_user
from utils.db_async import run_db

logger = logging.getLogger(__name__)


class UserRegistrationMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user:
            try:
                db_user = await run_db(get_or_create_user, user.id, user.full_name or "")
                data["db_user"] = db_user
            except Exception:
                logger.exception("Не удалось зарегистрировать пользователя %s", user.id)
        return await handler(event, data)
