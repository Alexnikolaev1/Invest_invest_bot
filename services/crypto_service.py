# services/crypto_service.py
"""
Получение данных по криптовалютам через CoinGecko API (бесплатно, без ключа).
Поддерживает известные тикеры и динамический поиск через CoinGecko Search API.
"""

import io
import logging
import aiohttp

from config import CACHE_TTL_CRYPTO_PRICE
from utils.cache import cache_get_async, cache_set_async
from utils.helpers import make_cache_key
from utils.db_async import run_db
from database import get_connection

logger = logging.getLogger(__name__)

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# Маппинг тикер -> id CoinGecko (наиболее популярные монеты)
TICKER_TO_ID = {
    "BTC": "bitcoin", "ETH": "ethereum", "USDT": "tether", "BNB": "binancecoin",
    "SOL": "solana", "XRP": "ripple", "USDC": "usd-coin", "ADA": "cardano",
    "DOGE": "dogecoin", "TON": "the-open-network", "TRX": "tron", "AVAX": "avalanche-2",
    "DOT": "polkadot", "MATIC": "matic-network", "LINK": "chainlink", "LTC": "litecoin",
    "SHIB": "shiba-inu", "BCH": "bitcoin-cash", "NEAR": "near", "UNI": "uniswap",
    "XLM": "stellar", "ATOM": "cosmos", "ETC": "ethereum-classic", "XMR": "monero",
    "FIL": "filecoin", "APT": "aptos", "ARB": "arbitrum", "OP": "optimism",
}

KNOWN_CRYPTO_TICKERS = frozenset(TICKER_TO_ID.keys())


class CryptoDataError(Exception):
    pass


def _normalize_ticker(ticker: str) -> str:
    upper = ticker.upper().strip()
    if upper.endswith("-USD"):
        upper = upper[:-4]
    return upper


def _save_ticker_mapping(ticker: str, coin_id: str) -> None:
    """Сохраняет найденный маппинг тикер→id для ускорения последующих запросов."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO cache (key, data, expires_at) VALUES (?, ?, NULL) "
            "ON CONFLICT(key) DO UPDATE SET data = excluded.data",
            (make_cache_key("crypto_id", ticker), f'"{coin_id}"'),
        )
        conn.commit()


def _get_cached_id(ticker: str) -> str | None:
    cache_key = make_cache_key("crypto_id", ticker)
    with get_connection() as conn:
        cur = conn.execute("SELECT data FROM cache WHERE key = ?", (cache_key,))
        row = cur.fetchone()
        if row:
            try:
                import json
                return json.loads(row["data"])
            except (json.JSONDecodeError, TypeError):
                return None
    return None


async def _search_coingecko_id(ticker: str) -> str | None:
    """Ищет coin id через CoinGecko Search API."""
    url = f"{COINGECKO_BASE}/search?query={ticker}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()

    coins = data.get("coins", [])
    ticker_upper = ticker.upper()
    for coin in coins:
        if coin.get("symbol", "").upper() == ticker_upper:
            coin_id = coin.get("id")
            if coin_id:
                await run_db(_save_ticker_mapping, ticker_upper, coin_id)
                TICKER_TO_ID[ticker_upper] = coin_id
                return coin_id
    return None


async def _resolve_id(ticker: str) -> str:
    ticker = _normalize_ticker(ticker)
    coin_id = TICKER_TO_ID.get(ticker) or _get_cached_id(ticker)
    if coin_id:
        return coin_id

    coin_id = await _search_coingecko_id(ticker)
    if coin_id:
        return coin_id

    raise CryptoDataError(
        f"Неизвестный тикер криптовалюты: {ticker}. "
        "Попробуйте стандартный символ, например BTC или ETH."
    )


async def get_crypto_data(ticker: str) -> dict:
    """Возвращает цену, капитализацию и изменение за 24ч/7д для монеты."""
    ticker = _normalize_ticker(ticker)
    cache_key = make_cache_key("crypto_data", ticker)
    cached = await cache_get_async(cache_key)
    if cached:
        return cached

    coin_id = await _resolve_id(ticker)
    url = (
        f"{COINGECKO_BASE}/coins/markets?vs_currency=usd&ids={coin_id}"
        f"&price_change_percentage=24h,7d"
    )

    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                raise CryptoDataError(f"CoinGecko вернул ошибку {resp.status}")
            data = await resp.json()

    if not data:
        raise CryptoDataError(f"CoinGecko не вернул данных для {ticker}")

    coin = data[0]
    result = {
        "ticker": ticker,
        "name": coin.get("name", ticker),
        "price": coin.get("current_price"),
        "market_cap": coin.get("market_cap"),
        "change_24h": coin.get("price_change_percentage_24h_in_currency"),
        "change_7d": coin.get("price_change_percentage_7d_in_currency"),
        "ath": coin.get("ath"),
        "atl": coin.get("atl"),
        "volume_24h": coin.get("total_volume"),
        "source": "coingecko",
    }
    await cache_set_async(cache_key, result, CACHE_TTL_CRYPTO_PRICE)
    return result


async def get_crypto_history(ticker: str, days: int = 365):
    """Возвращает список [timestamp_ms, price] за указанный период."""
    coin_id = await _resolve_id(ticker)
    url = f"{COINGECKO_BASE}/coins/{coin_id}/market_chart?vs_currency=usd&days={days}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                raise CryptoDataError(f"CoinGecko вернул ошибку {resp.status}")
            data = await resp.json()

    prices = data.get("prices")
    if not prices:
        raise CryptoDataError(f"Нет исторических данных для {ticker}")
    return prices


async def build_crypto_chart(ticker: str, days: int = 365) -> io.BytesIO:
    """Строит график цены криптовалюты за период и возвращает PNG в BytesIO."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from datetime import datetime

    prices = await get_crypto_history(ticker, days)
    dates = [datetime.fromtimestamp(p[0] / 1000) for p in prices]
    values = [p[1] for p in prices]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(dates, values, color="#e9902b", linewidth=1.8)
    ax.set_title(f"{ticker.upper()} — цена за {days} дн.")
    ax.set_xlabel("Дата")
    ax.set_ylabel("Цена, $")
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf
