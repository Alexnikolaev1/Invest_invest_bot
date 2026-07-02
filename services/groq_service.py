# services/groq_service.py
"""
Транскрибация голосовых сообщений через Groq Whisper Large v3.
"""

import logging
import aiohttp

from config import GROQ_API_KEY

logger = logging.getLogger(__name__)

GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


class GroqTranscriptionError(Exception):
    pass


async def transcribe_voice(file_bytes: bytes, filename: str = "voice.ogg") -> str:
    """
    Отправляет аудиофайл в Groq Whisper Large v3 и возвращает распознанный текст.
    """
    if not GROQ_API_KEY:
        raise GroqTranscriptionError("GROQ_API_KEY не задан в переменных окружения.")

    form = aiohttp.FormData()
    form.add_field("file", file_bytes, filename=filename, content_type="audio/ogg")
    form.add_field("model", "whisper-large-v3")
    form.add_field("language", "ru")

    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                GROQ_TRANSCRIPTION_URL, data=form, headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error("Groq API error %s: %s", resp.status, text)
                    raise GroqTranscriptionError(f"Groq вернул ошибку {resp.status}")
                data = await resp.json()
    except aiohttp.ClientError as exc:
        logger.exception("Сетевая ошибка при обращении к Groq")
        raise GroqTranscriptionError("Сетевая ошибка при распознавании голоса.") from exc

    text = data.get("text", "").strip()
    if not text:
        raise GroqTranscriptionError("Не удалось распознать голосовое сообщение.")
    return text
