"""Ограничение доступа к боту по Telegram user id."""

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update, User

from config import ALLOWED_USER_IDS

logger = logging.getLogger(__name__)

DENY_TEXT = "⛔ Этот бот доступен только владельцу."


def extract_user(event: TelegramObject) -> User | None:
    if isinstance(event, Update):
        for attr in (
            "message", "edited_message", "callback_query",
            "inline_query", "chosen_inline_result",
        ):
            inner = getattr(event, attr, None)
            if inner is not None:
                user = getattr(inner, "from_user", None)
                if user:
                    return user
        return None

    return getattr(event, "from_user", None)


async def _notify_denied(event: TelegramObject) -> None:
    try:
        if isinstance(event, Update) and event.callback_query:
            await event.callback_query.answer(DENY_TEXT, show_alert=True)
            return
        if isinstance(event, Update) and event.message:
            await event.message.answer(DENY_TEXT)
            return
        if isinstance(event, CallbackQuery):
            await event.answer(DENY_TEXT, show_alert=True)
            return
        if isinstance(event, Message):
            await event.answer(DENY_TEXT)
    except Exception:
        logger.debug("Не удалось отправить отказ неавторизованному пользователю", exc_info=True)


class AccessControlMiddleware(BaseMiddleware):
    """Пропускает только пользователей из ALLOWED_USER_IDS (если переменная задана)."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if ALLOWED_USER_IDS is None:
            return await handler(event, data)

        user = extract_user(event)
        if user is None:
            return await handler(event, data)

        if user.id not in ALLOWED_USER_IDS:
            logger.warning("Отказ в доступе: user_id=%s", user.id)
            await _notify_denied(event)
            return None

        return await handler(event, data)
