# utils/helpers.py
"""Вспомогательные функции общего назначения."""

import hashlib


def make_cache_key(*parts: str) -> str:
    """Строит стабильный ключ кэша из произвольных строковых частей."""
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def format_number(value: float, decimals: int = 2) -> str:
    """Форматирует число с разделителями тысяч и фиксированным числом знаков."""
    if value is None:
        return "н/д"
    try:
        return f"{value:,.{decimals}f}".replace(",", " ")
    except (ValueError, TypeError):
        return "н/д"


def format_percent(value: float, decimals: int = 2) -> str:
    if value is None:
        return "н/д"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.{decimals}f}%"


def format_currency(value: float, currency: str = "USD", decimals: int = 2) -> str:
    if value is None:
        return "н/д"
    symbols = {"USD": "$", "EUR": "€", "RUB": "₽"}
    symbol = symbols.get(currency, currency + " ")
    return f"{symbol}{format_number(value, decimals)}"


def is_crypto_ticker(ticker: str) -> bool:
    """
    Эвристика: известные криптотикеры + суффикс -USD (например BTC-USD).
    Динамический поиск неизвестных тикеров выполняет crypto_service.
    """
    from services.crypto_service import KNOWN_CRYPTO_TICKERS

    upper = ticker.upper().strip()
    if upper.endswith("-USD"):
        upper = upper[:-4]
    return upper in KNOWN_CRYPTO_TICKERS
