"""Тесты middleware доступа."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from middlewares.access import AccessControlMiddleware, extract_user, DENY_TEXT


def _make_message(user_id: int) -> Message:
    user = User(id=user_id, is_bot=False, first_name="Test")
    chat = Chat(id=user_id, type="private")
    return Message(message_id=1, date=0, chat=chat, from_user=user)


def _make_callback(user_id: int) -> CallbackQuery:
    user = User(id=user_id, is_bot=False, first_name="Test")
    chat = Chat(id=user_id, type="private")
    message = Message(message_id=1, date=0, chat=chat, from_user=user)
    return CallbackQuery(id="1", from_user=user, chat_instance="x", message=message)


class TestExtractUser:
    def test_from_message_update(self):
        msg = _make_message(12345)
        update = Update(update_id=1, message=msg)
        assert extract_user(update).id == 12345

    def test_from_callback_update(self):
        cb = _make_callback(999)
        update = Update(update_id=2, callback_query=cb)
        assert extract_user(update).id == 999


class TestAccessControlMiddleware:
    @pytest.mark.asyncio
    async def test_allows_owner(self, monkeypatch):
        monkeypatch.setattr("middlewares.access.ALLOWED_USER_IDS", frozenset({42}))
        middleware = AccessControlMiddleware()
        handler = AsyncMock(return_value="ok")
        msg = _make_message(42)
        update = Update(update_id=1, message=msg)

        result = await middleware(handler, update, {})

        assert result == "ok"
        handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_blocks_stranger(self, monkeypatch):
        monkeypatch.setattr("middlewares.access.ALLOWED_USER_IDS", frozenset({42}))
        monkeypatch.setattr(
            "middlewares.access._notify_denied", AsyncMock(),
        )
        middleware = AccessControlMiddleware()
        handler = AsyncMock()
        update = Update(update_id=1, message=_make_message(100))

        result = await middleware(handler, update, {})

        assert result is None
        handler.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_allows_any_from_list(self, monkeypatch):
        monkeypatch.setattr("middlewares.access.ALLOWED_USER_IDS", frozenset({42, 99}))
        middleware = AccessControlMiddleware()
        handler = AsyncMock(return_value="ok")
        update = Update(update_id=1, message=_make_message(99))

        result = await middleware(handler, update, {})

        assert result == "ok"
        handler.assert_awaited_once()
