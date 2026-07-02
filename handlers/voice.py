# handlers/voice.py
"""
Обработка голосовых сообщений: скачиваем аудио, транскрибируем через Groq Whisper,
затем по ключевым словам определяем намерение (анализ тикера или новости).
"""

import re
import logging

from aiogram import Router, Bot
from aiogram.filters import CommandObject
from aiogram.types import Message

from services.groq_service import transcribe_voice, GroqTranscriptionError
from utils.text import esc

logger = logging.getLogger(__name__)
router = Router(name="voice")

ANALYSE_KEYWORDS = ("анализ", "проанализируй", "оцени")
NEWS_KEYWORDS = ("новости", "новость")

TICKER_PATTERN = re.compile(r"\b[A-ZА-Я]{2,6}\b")


@router.message(lambda message: message.voice is not None)
async def handle_voice(message: Message, bot: Bot, db_user: dict = None):
    status_msg = await message.answer("🎙 Распознаю голосовое сообщение...")

    try:
        file = await bot.get_file(message.voice.file_id)
        file_bytes_io = await bot.download_file(file.file_path)
        file_bytes = file_bytes_io.read()
        text = await transcribe_voice(file_bytes, filename="voice.ogg")
    except GroqTranscriptionError as exc:
        await status_msg.edit_text(f"❌ {esc(exc)}")
        return
    except Exception:
        logger.exception("Ошибка при обработке голосового сообщения")
        await status_msg.edit_text("❌ Не удалось обработать голосовое сообщение.")
        return

    await status_msg.edit_text(f"📝 Распознано: «{esc(text)}»")

    lowered = text.lower()
    tickers_found = TICKER_PATTERN.findall(text.upper())

    if any(kw in lowered for kw in ANALYSE_KEYWORDS) and tickers_found:
        from handlers.analyse import cmd_analyse
        await cmd_analyse(
            message, CommandObject(command="analyse", args=tickers_found[0]),
            db_user=db_user,
        )
        return

    if any(kw in lowered for kw in NEWS_KEYWORDS):
        from handlers.news import cmd_news
        query = lowered
        for kw in NEWS_KEYWORDS:
            query = query.replace(kw, "")
        query = query.strip() or text
        await cmd_news(message, CommandObject(command="news", args=query))
        return

    await message.answer(
        "Не удалось однозначно распознать команду по голосу.\n"
        "Попробуйте, например, текстом: <code>/analyse AAPL</code> или "
        "<code>/news Tesla</code>.",
    )
