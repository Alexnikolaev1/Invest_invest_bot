# utils/rate_limiter.py
"""
Асинхронный rate limiter.
- Ограничивает количество запросов к Gemini на пользователя в минуту
  и общее число запросов в минуту (глобально).
- Дневные лимиты (GNews, Alpha Vantage) отслеживаются через таблицу counters
  в database.py (increment_counter / get_counter).
"""

import time
import asyncio
from collections import defaultdict, deque

from config import GEMINI_PER_USER_PER_MIN, GEMINI_GLOBAL_PER_MIN


class SlidingWindowLimiter:
    """Скользящее окно в 60 секунд для ограничения частоты запросов."""

    def __init__(self):
        self._per_user: dict[int, deque] = defaultdict(deque)
        self._global: deque = deque()
        self._lock = asyncio.Lock()

    async def allow(self, user_id: int) -> bool:
        """
        Проверяет, можно ли пользователю выполнить запрос к Gemini прямо сейчас.
        Если да - регистрирует запрос и возвращает True, иначе False.
        """
        now = time.monotonic()
        async with self._lock:
            self._trim(self._global, now)
            self._trim(self._per_user[user_id], now)

            if len(self._global) >= GEMINI_GLOBAL_PER_MIN:
                return False
            if len(self._per_user[user_id]) >= GEMINI_PER_USER_PER_MIN:
                return False

            self._global.append(now)
            self._per_user[user_id].append(now)
            return True

    @staticmethod
    def _trim(dq: deque, now: float, window: float = 60.0) -> None:
        while dq and now - dq[0] > window:
            dq.popleft()


# Единый инстанс лимитера на весь процесс бота
gemini_limiter = SlidingWindowLimiter()
