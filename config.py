# config.py
"""
Конфигурация бота INVESTMIND AI.
Все чувствительные данные берутся из переменных окружения (Railway Variables).
"""

import os

# ---------- Основные токены ----------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# ---------- Опциональные ключи (фолбэки) ----------
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")
GNEWS_API_KEY = os.getenv("GNEWS_API_KEY", "")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")

# ---------- Вебхук / поллинг ----------
WEBHOOK_URL = os.getenv("WEBHOOK_URL") or os.getenv("RAILWAY_STATIC_URL")
WEBHOOK_PATH = "/webhook"
PORT = int(os.getenv("PORT", 8000))
USE_WEBHOOK = bool(WEBHOOK_URL)

# ---------- База данных ----------
DB_PATH = os.getenv("DB_PATH", "investmind.db")

# ---------- Gemini ----------
# Используем бесплатную модель Gemini (актуальную на момент написания).
# При необходимости можно сменить в переменных окружения.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_API_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

# ---------- Rate limiting ----------
GEMINI_PER_USER_PER_MIN = 5
GEMINI_GLOBAL_PER_MIN = 14
NEWS_DAILY_LIMIT = 100          # GNews / NewsAPI
ALPHA_VANTAGE_DAILY_LIMIT = 25
COINGECKO_PER_MIN = 45          # с запасом от лимита 50/мин

# ---------- Кэширование (в секундах) ----------
CACHE_TTL_LESSON = None          # бессрочно
CACHE_TTL_STOCK_PRICE = 15 * 60      # 15 минут
CACHE_TTL_STOCK_MULTIPLES = 60 * 60  # 1 час
CACHE_TTL_NEWS = 30 * 60             # 30 минут
CACHE_TTL_CRYPTO_PRICE = 60          # 1 минута
CACHE_TTL_CRYPTO_MULTIPLES = 60 * 60 # 1 час

# ---------- Прочее ----------
DISCLAIMER = (
    "⚠️ <b>INVESTMIND AI</b> — образовательный и аналитический инструмент.\n"
    "Бот не даёт инвестиционных рекомендаций и не несёт ответственности "
    "за ваши финансовые решения. Все выводы носят ознакомительный характер.\n"
    "Инвестиции сопряжены с риском."
)

TTS_VOICE = "ru-RU-SvetlanaNeural"
TTS_MIN_LENGTH = 300  # озвучиваем ответы длиннее этого числа символов

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ---------- Доступ ----------
# Если задан — бот отвечает только указанным Telegram user id.
# Один id: ALLOWED_USER_ID=123456789
# Несколько через запятую: ALLOWED_USER_ID=123456789,987654321
def _parse_allowed_user_ids() -> frozenset[int] | None:
    raw = os.getenv("ALLOWED_USER_ID", "").strip()
    if not raw:
        return None

    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            user_id = int(part)
        except ValueError as exc:
            raise RuntimeError(
                "ALLOWED_USER_ID должен содержать целые числа через запятую "
                "(Telegram user id), например: 123456789 или 123,456,789"
            ) from exc
        if user_id <= 0:
            raise RuntimeError("ALLOWED_USER_ID: каждый id должен быть положительным числом.")
        ids.add(user_id)

    if not ids:
        return None
    return frozenset(ids)


ALLOWED_USER_IDS = _parse_allowed_user_ids()
