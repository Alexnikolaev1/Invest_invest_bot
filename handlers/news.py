# handlers/news.py
"""
Команда /news <тикер или тема> — сводка новостей с анализом тональности через Gemini.
"""

import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from services.news_service import get_news, NewsDataError
from services.gemini_service import ask_gemini, GeminiRateLimitExceeded, GeminiRequestError
from utils.text import esc

logger = logging.getLogger(__name__)
router = Router(name="news")

NEWS_SYSTEM_PROMPT = (
    "Ты — финансовый аналитик. На основе заголовков и описаний новостей определи "
    "преобладающую тональность (позитивная/негативная/нейтральная), выдели главные темы "
    "и объясни возможное влияние на цену актива. Будь краток и структурирован."
)


@router.message(Command("news"))
async def cmd_news(message: Message, command: CommandObject):
    if not command.args:
        await message.answer(
            "Использование: <code>/news Tesla</code> или <code>/news нефть</code>",
        )
        return

    query = command.args.strip()
    status_msg = await message.answer(f"⏳ Ищу новости по запросу «{esc(query)}»...")

    try:
        articles = await get_news(query, max_articles=7)
    except NewsDataError as exc:
        await status_msg.edit_text(f"❌ {esc(exc)}")
        return

    if not articles:
        await status_msg.edit_text(f"По запросу «{esc(query)}» новостей не найдено.")
        return

    headlines_block = "\n".join(
        f"- {a['title']}: {a.get('description', '')}" for a in articles
    )
    prompt = f"Тема: {query}\n\nНовости:\n{headlines_block}"

    try:
        sentiment_analysis = await ask_gemini(message.from_user.id, prompt, NEWS_SYSTEM_PROMPT)
    except GeminiRateLimitExceeded as exc:
        await status_msg.edit_text(f"⏱ {esc(exc)}")
        return
    except GeminiRequestError as exc:
        sentiment_analysis = f"(Не удалось получить AI-анализ тональности: {exc})"

    articles_text = "\n\n".join(
        f"📰 <a href=\"{esc(a['url'])}\">{esc(a['title'])}</a>\n"
        f"<i>{esc(a.get('source', ''))}</i>"
        for a in articles[:5]
    )

    await status_msg.delete()
    await message.answer(
        f"📰 <b>Новости по теме: {esc(query)}</b>\n\n{articles_text}\n\n"
        f"<b>🧠 Анализ тональности AI:</b>\n{esc(sentiment_analysis)}",
        disable_web_page_preview=True,
    )
