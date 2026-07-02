# utils/cache.py
"""
Простой TTL-кэш поверх таблицы `cache` в SQLite.
Используется для уроков (бессрочно), цен акций/крипты, новостей и т.д.
"""

import json
import time
import logging
from typing import Any, Optional

from database import get_connection

logger = logging.getLogger(__name__)


def cache_set(key: str, data: Any, ttl_seconds: Optional[int] = None) -> None:
    """
    Сохраняет данные в кэш.
    ttl_seconds=None -> кэш бессрочный (например, уроки).
    """
    expires_at = None
    if ttl_seconds is not None:
        expires_at = int(time.time()) + ttl_seconds

    payload = json.dumps(data, ensure_ascii=False)
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO cache (key, data, expires_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET data = excluded.data, "
            "expires_at = excluded.expires_at",
            (key, payload, expires_at),
        )
        conn.commit()


def cache_get(key: str) -> Optional[Any]:
    """Возвращает данные из кэша, если они ещё не истекли, иначе None."""
    with get_connection() as conn:
        cur = conn.execute("SELECT data, expires_at FROM cache WHERE key = ?", (key,))
        row = cur.fetchone()
        if row is None:
            return None
        expires_at = row["expires_at"]
        if expires_at is not None and int(time.time()) > expires_at:
            # Кэш истёк - удаляем и возвращаем None
            conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            conn.commit()
            return None
        try:
            return json.loads(row["data"])
        except (json.JSONDecodeError, TypeError):
            logger.warning("Не удалось декодировать кэш для ключа %s", key)
            return None


def cache_delete(key: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM cache WHERE key = ?", (key,))
        conn.commit()


async def cache_get_async(key: str) -> Optional[Any]:
    from utils.db_async import run_db
    return await run_db(cache_get, key)


async def cache_set_async(key: str, data: Any, ttl_seconds: Optional[int] = None) -> None:
    from utils.db_async import run_db
    await run_db(cache_set, key, data, ttl_seconds)
