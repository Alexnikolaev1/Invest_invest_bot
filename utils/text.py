"""Утилиты форматирования текста для Telegram HTML."""

import html
import re


def esc(text: object) -> str:
    """Экранирует спецсимволы HTML в пользовательском/AI-контенте."""
    return html.escape(str(text or ""))


def md_to_html(text: str) -> str:
    """Конвертирует базовый Markdown (*bold*, _italic_) в HTML для совместимости."""
    if not text:
        return ""
    result = esc(text)
    result = re.sub(r"\*([^*]+)\*", r"<b>\1</b>", result)
    result = re.sub(r"_([^_]+)_", r"<i>\1</i>", result)
    return result
