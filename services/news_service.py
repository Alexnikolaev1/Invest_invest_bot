# services/news_service.py
"""
Получение новостей по компании/теме через GNews API (основной) или NewsAPI (фолбэк).
Оба сервиса имеют дневные лимиты, которые отслеживаются через counters в БД.
"""

import logging
from urllib.parse import quote_plus

import aiohttp

from config import (
    GNEWS_API_KEY, NEWSAPI_KEY, NEWS_DAILY_LIMIT, CACHE_TTL_NEWS,
)
from utils.cache import cache_get_async, cache_set_async
from utils.helpers import make_cache_key
from utils.db_async import run_db
from database import get_counter, increment_counter

logger = logging.getLogger(__name__)


class NewsDataError(Exception):
    pass


class NewsQuotaExceeded(Exception):
    pass


async def get_news(query: str, max_articles: int = 7) -> list[dict]:
    """
    Возвращает список новостей: [{title, description, url, source, published_at}, ...]
    Порядок источников: кэш -> GNews -> NewsAPI -> ошибка.
    """
    cache_key = make_cache_key("news", query.lower())
    cached = await cache_get_async(cache_key)
    if cached:
        return cached

    gnews_count = await run_db(get_counter, "gnews")
    if GNEWS_API_KEY and gnews_count < NEWS_DAILY_LIMIT:
        try:
            articles = await _fetch_gnews(query, max_articles)
            await run_db(increment_counter, "gnews")
            await cache_set_async(cache_key, articles, CACHE_TTL_NEWS)
            return articles
        except Exception as exc:
            logger.warning("GNews не смог получить новости по '%s': %s", query, exc)

    newsapi_count = await run_db(get_counter, "newsapi")
    if NEWSAPI_KEY and newsapi_count < NEWS_DAILY_LIMIT:
        try:
            articles = await _fetch_newsapi(query, max_articles)
            await run_db(increment_counter, "newsapi")
            await cache_set_async(cache_key, articles, CACHE_TTL_NEWS)
            return articles
        except Exception as exc:
            logger.warning("NewsAPI не смог получить новости по '%s': %s", query, exc)

    raise NewsDataError(
        "Не удалось получить новости: сервисы недоступны или дневной лимит запросов исчерпан."
    )


async def _fetch_gnews(query: str, max_articles: int) -> list[dict]:
    encoded = quote_plus(query)
    url = (
        f"https://gnews.io/api/v4/search?q={encoded}&lang=ru&max={max_articles}"
        f"&apikey={GNEWS_API_KEY}"
    )
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                raise NewsDataError(f"GNews вернул ошибку {resp.status}")
            data = await resp.json()

    articles = data.get("articles", [])
    return [
        {
            "title": a.get("title", ""),
            "description": a.get("description", ""),
            "url": a.get("url", ""),
            "source": a.get("source", {}).get("name", ""),
            "published_at": a.get("publishedAt", ""),
        }
        for a in articles
    ]


async def _fetch_newsapi(query: str, max_articles: int) -> list[dict]:
    encoded = quote_plus(query)
    url = (
        f"https://newsapi.org/v2/everything?q={encoded}&language=ru"
        f"&pageSize={max_articles}&sortBy=publishedAt&apiKey={NEWSAPI_KEY}"
    )
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                raise NewsDataError(f"NewsAPI вернул ошибку {resp.status}")
            data = await resp.json()

    articles = data.get("articles", [])
    return [
        {
            "title": a.get("title", ""),
            "description": a.get("description", ""),
            "url": a.get("url", ""),
            "source": a.get("source", {}).get("name", ""),
            "published_at": a.get("publishedAt", ""),
        }
        for a in articles
    ]
