# services/tts.py
"""
Озвучка текста через Microsoft Edge TTS (библиотека edge-tts).
Используется для длинных аналитических ответов (>300 символов).
"""

import os
import tempfile
import uuid
import logging

import edge_tts

from config import TTS_VOICE

logger = logging.getLogger(__name__)


async def text_to_speech_file(text: str) -> str:
    """
    Генерирует mp3-файл с озвучкой текста и возвращает путь к нему.
    Вызывающий код обязан удалить файл после отправки пользователю.
    """
    # Ограничиваем длину текста, чтобы не создавать слишком долгие аудио
    trimmed_text = text[:2000]

    filename = f"tts_{uuid.uuid4().hex}.mp3"
    filepath = os.path.join(tempfile.gettempdir(), filename)

    communicate = edge_tts.Communicate(trimmed_text, voice=TTS_VOICE)
    await communicate.save(filepath)

    return filepath


def cleanup_file(filepath: str) -> None:
    """Удаляет временный аудиофайл."""
    try:
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
    except OSError as exc:
        logger.warning("Не удалось удалить временный файл %s: %s", filepath, exc)
