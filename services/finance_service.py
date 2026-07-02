# services/finance_service.py
"""
Получение данных по акциям.
Основной источник - yfinance (бесплатно, без ключа).
Фолбэк - Alpha Vantage (25 запросов/день), только цена и мультипликаторы.

yfinance синхронный, поэтому все вызовы оборачиваются в run_in_executor,
чтобы не блокировать event loop aiogram.
"""

import io
import asyncio
import logging
from datetime import datetime

import aiohttp

from config import ALPHA_VANTAGE_API_KEY, CACHE_TTL_STOCK_PRICE, CACHE_TTL_STOCK_MULTIPLES
from utils.cache import cache_get_async, cache_set_async
from utils.helpers import make_cache_key
from utils.db_async import run_db
from database import increment_counter, get_counter
from config import ALPHA_VANTAGE_DAILY_LIMIT

logger = logging.getLogger(__name__)


class FinanceDataError(Exception):
    """Не удалось получить данные ни из одного источника."""


def _fetch_yfinance_sync(ticker: str) -> dict:
    """Синхронная функция для запуска в executor - тянет данные из yfinance."""
    import yfinance as yf

    tk = yf.Ticker(ticker)
    info = tk.info  # может кинуть исключение, если тикер не найден

    if not info or info.get("regularMarketPrice") is None and info.get("currentPrice") is None:
        raise FinanceDataError(f"Тикер {ticker} не найден в Yahoo Finance.")

    price = info.get("currentPrice") or info.get("regularMarketPrice")

    return {
        "ticker": ticker.upper(),
        "name": info.get("longName") or info.get("shortName") or ticker.upper(),
        "price": price,
        "pe": info.get("trailingPE"),
        "ps": info.get("priceToSalesTrailing12Months"),
        "ev_ebitda": info.get("enterpriseToEbitda"),
        "dividend_yield": (info.get("dividendYield") or 0) * 100 if info.get("dividendYield") else None,
        "week52_low": info.get("fiftyTwoWeekLow"),
        "week52_high": info.get("fiftyTwoWeekHigh"),
        "beta": info.get("beta"),
        "market_cap": info.get("marketCap"),
        "currency": info.get("currency", "USD"),
        "source": "yfinance",
    }


def _fetch_yfinance_history_sync(ticker: str, period: str = "1y"):
    """Синхронная функция - тянет историю цен за период (для графика)."""
    import yfinance as yf

    tk = yf.Ticker(ticker)
    hist = tk.history(period=period)
    if hist.empty:
        raise FinanceDataError(f"Нет исторических данных для {ticker}.")
    return hist


async def get_stock_data(ticker: str) -> dict:
    """
    Возвращает словарь с ценой и мультипликаторами для тикера.
    Порядок: кэш -> yfinance -> Alpha Vantage (фолбэк) -> ошибка.
    """
    ticker = ticker.upper().strip()
    cache_key = make_cache_key("stock_data", ticker)
    cached = await cache_get_async(cache_key)
    if cached:
        return cached

    loop = asyncio.get_running_loop()
    try:
        data = await loop.run_in_executor(None, _fetch_yfinance_sync, ticker)
        await cache_set_async(cache_key, data, CACHE_TTL_STOCK_MULTIPLES)
        return data
    except Exception as exc:
        logger.warning("yfinance не смог получить данные по %s: %s", ticker, exc)

    # Фолбэк на Alpha Vantage
    av_count = await run_db(get_counter, "alpha_vantage")
    if ALPHA_VANTAGE_API_KEY and av_count < ALPHA_VANTAGE_DAILY_LIMIT:
        try:
            data = await _fetch_alpha_vantage(ticker)
            await run_db(increment_counter, "alpha_vantage")
            await cache_set_async(cache_key, data, CACHE_TTL_STOCK_MULTIPLES)
            return data
        except Exception as exc:
            logger.warning("Alpha Vantage тоже не смог получить данные по %s: %s", ticker, exc)

    raise FinanceDataError(
        f"Не удалось получить данные по тикеру {ticker}. Сервис временно недоступен."
    )


async def _fetch_alpha_vantage(ticker: str) -> dict:
    """Запрос к Alpha Vantage (OVERVIEW + GLOBAL_QUOTE) для базовых метрик."""
    async with aiohttp.ClientSession() as session:
        overview_url = (
            f"https://www.alphavantage.co/query?function=OVERVIEW"
            f"&symbol={ticker}&apikey={ALPHA_VANTAGE_API_KEY}"
        )
        quote_url = (
            f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE"
            f"&symbol={ticker}&apikey={ALPHA_VANTAGE_API_KEY}"
        )
        async with session.get(overview_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            overview = await resp.json()
        async with session.get(quote_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            quote = await resp.json()

    if not overview or overview.get("Symbol") is None:
        raise FinanceDataError(f"Alpha Vantage не нашёл тикер {ticker}.")

    global_quote = quote.get("Global Quote", {})
    price = global_quote.get("05. price")

    def _to_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    return {
        "ticker": ticker.upper(),
        "name": overview.get("Name", ticker.upper()),
        "price": _to_float(price),
        "pe": _to_float(overview.get("PERatio")),
        "ps": _to_float(overview.get("PriceToSalesRatioTTM")),
        "ev_ebitda": _to_float(overview.get("EVToEBITDA")),
        "dividend_yield": _to_float(overview.get("DividendYield")) * 100
        if overview.get("DividendYield") else None,
        "week52_low": _to_float(overview.get("52WeekLow")),
        "week52_high": _to_float(overview.get("52WeekHigh")),
        "beta": _to_float(overview.get("Beta")),
        "market_cap": _to_float(overview.get("MarketCapitalization")),
        "currency": overview.get("Currency", "USD"),
        "source": "alpha_vantage",
    }


async def get_stock_history(ticker: str, period: str = "1y"):
    """Возвращает объект pandas.DataFrame с историей цен (для построения графика)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch_yfinance_history_sync, ticker, period)


async def build_price_chart(ticker: str, period: str = "1y") -> io.BytesIO:
    """Строит график цены за период и возвращает PNG-изображение в BytesIO."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    hist = await get_stock_history(ticker, period)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(hist.index, hist["Close"], color="#2b7de9", linewidth=1.8)
    ax.set_title(f"{ticker.upper()} — цена за {period}")
    ax.set_xlabel("Дата")
    ax.set_ylabel("Цена")
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf
