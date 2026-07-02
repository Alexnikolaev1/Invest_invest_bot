# services/gemini_service.py
"""
Обёртка для запросов к Google Gemini API (бесплатный тир).
Учитывает rate limiting (5 запросов/мин на пользователя, 14/мин глобально).
"""

import logging
import aiohttp

from config import GEMINI_API_KEY, GEMINI_API_URL
from utils.rate_limiter import gemini_limiter

logger = logging.getLogger(__name__)


class GeminiRateLimitExceeded(Exception):
    """Выбрасывается, когда пользователь или система превысили лимит запросов."""


class GeminiRequestError(Exception):
    """Общая ошибка при обращении к Gemini API."""


async def ask_gemini(user_id: int, prompt: str, system_instruction: str = "") -> str:
    """
    Отправляет запрос к Gemini и возвращает текстовый ответ.
    Бросает GeminiRateLimitExceeded, если лимит исчерпан.
    """
    allowed = await gemini_limiter.allow(user_id)
    if not allowed:
        raise GeminiRateLimitExceeded(
            "Превышен лимит запросов к AI. Пожалуйста, подождите минуту и попробуйте снова."
        )

    if not GEMINI_API_KEY:
        raise GeminiRequestError("GEMINI_API_KEY не задан в переменных окружения.")

    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.6,
            "maxOutputTokens": 1500,
        },
    }
    if system_instruction:
        body["systemInstruction"] = {"parts": [{"text": system_instruction}]}

    headers = {"x-goog-api-key": GEMINI_API_KEY}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                GEMINI_API_URL, json=body, headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error("Gemini API error %s: %s", resp.status, text)
                    raise GeminiRequestError(f"Gemini API вернул ошибку {resp.status}")
                data = await resp.json()
    except aiohttp.ClientError as exc:
        logger.exception("Сетевая ошибка при обращении к Gemini")
        raise GeminiRequestError("Сетевая ошибка при обращении к AI-сервису.") from exc

    try:
        candidates = data.get("candidates", [])
        if not candidates:
            raise GeminiRequestError("Gemini не вернул ответа (пустой candidates).")
        parts = candidates[0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts)
        return text.strip()
    except (KeyError, IndexError) as exc:
        logger.exception("Неожиданный формат ответа Gemini: %s", data)
        raise GeminiRequestError("Не удалось разобрать ответ AI-сервиса.") from exc
