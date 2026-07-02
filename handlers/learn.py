# handlers/learn.py
"""
Встроенный обучающий курс.
/learn -> дерево тем -> Gemini генерирует урок (кэшируется навсегда для темы+уровня)
-> после урока мини-квиз (3-5 вопросов, генерируется Gemini в фиксированном JSON-формате).
"""

import json
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from database import save_education_progress, get_or_create_user
from services.gemini_service import ask_gemini, GeminiRateLimitExceeded, GeminiRequestError
from utils.cache import cache_get_async, cache_set_async
from utils.helpers import make_cache_key
from utils.db_async import run_db
from utils.text import esc
from config import CACHE_TTL_LESSON

logger = logging.getLogger(__name__)
router = Router(name="learn")

TOPICS = {
    "basics": "Основы фондового рынка",
    "fundamental": "Фундаментальный анализ",
    "technical": "Технический анализ",
    "macro": "Макроэкономика для инвестора",
    "crypto": "Криптовалюта и блокчейн",
    "risk_psych": "Управление рисками и психология",
}


class QuizState(StatesGroup):
    in_progress = State()


def topics_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=name, callback_data=f"topic:{key}")]
        for key, name in TOPICS.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_topics(message: Message):
    await message.answer(
        "📚 <b>Выберите тему для изучения:</b>",
        reply_markup=topics_keyboard(),
    )


@router.message(Command("learn"))
async def cmd_learn(message: Message):
    await show_topics(message)


async def _get_user_level(user_id: int, db_user=None) -> str:
    if db_user:
        return db_user["level"] or "beginner"
    user = await run_db(get_or_create_user, user_id)
    return user["level"] or "beginner"


@router.callback_query(F.data.startswith("topic:"))
async def process_topic(callback: CallbackQuery, state: FSMContext, db_user: dict = None):
    topic_key = callback.data.split(":")[1]
    topic_name = TOPICS.get(topic_key, topic_key)

    level = await _get_user_level(callback.from_user.id, db_user)

    await callback.answer("Генерирую урок...")
    await callback.message.answer("⏳ Готовлю урок, это может занять несколько секунд...")

    cache_key = make_cache_key("lesson", topic_key, level)
    lesson_text = await cache_get_async(cache_key)

    if not lesson_text:
        prompt = (
            f"Ты — преподаватель инвестиций. Напиши структурированный, понятный урок "
            f"на тему «{topic_name}» для ученика с уровнем «{level}» "
            f"(beginner/intermediate/advanced). Урок должен быть практичным, "
            f"с примерами, без воды, объёмом примерно 300-500 слов. "
            f"Используй простые заголовки и списки."
        )
        try:
            lesson_text = await ask_gemini(callback.from_user.id, prompt)
            await cache_set_async(cache_key, lesson_text, CACHE_TTL_LESSON)
        except GeminiRateLimitExceeded as exc:
            await callback.message.answer(f"⏱ {esc(exc)}")
            return
        except GeminiRequestError as exc:
            await callback.message.answer(f"❌ Ошибка при генерации урока: {esc(exc)}")
            return

    await callback.message.answer(
        f"📖 <b>{esc(topic_name)}</b>\n\n{esc(lesson_text)}",
    )

    quiz_button = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(
            text="✅ Пройти мини-квиз", callback_data=f"quiz_start:{topic_key}",
        )]]
    )
    await callback.message.answer("Готовы проверить себя?", reply_markup=quiz_button)


async def generate_quiz(topic_name: str, level: str, user_id: int) -> list[dict]:
    """
    Просит Gemini сгенерировать квиз в строгом JSON-формате:
    [{"question": "...", "options": ["...","...","...","..."], "correct_index": 0}, ...]
    """
    prompt = (
        f"Составь мини-квиз из 4 вопросов по теме «{topic_name}» для уровня «{level}». "
        f"Ответь СТРОГО в формате JSON-массива без каких-либо пояснений и без markdown-разметки, "
        f'например: [{{"question": "текст вопроса", "options": ["в1", "в2", "в3", "в4"], '
        f'"correct_index": 0}}, ...]. correct_index - индекс правильного варианта (0-3).'
    )
    raw = await ask_gemini(user_id, prompt)

    cleaned = raw.strip().strip("`")
    if cleaned.lower().startswith("json"):
        cleaned = cleaned[4:].strip()

    try:
        quiz = json.loads(cleaned)
        assert isinstance(quiz, list) and len(quiz) > 0
        return quiz
    except (json.JSONDecodeError, AssertionError) as exc:
        logger.error("Не удалось распарсить квиз от Gemini: %s | raw=%s", exc, raw)
        raise GeminiRequestError("Не удалось сгенерировать квиз, попробуйте ещё раз.")


@router.callback_query(F.data.startswith("quiz_start:"))
async def quiz_start(callback: CallbackQuery, state: FSMContext, db_user: dict = None):
    topic_key = callback.data.split(":")[1]
    topic_name = TOPICS.get(topic_key, topic_key)

    level = await _get_user_level(callback.from_user.id, db_user)

    await callback.answer("Генерирую квиз...")

    try:
        quiz = await generate_quiz(topic_name, level, callback.from_user.id)
    except GeminiRateLimitExceeded as exc:
        await callback.message.answer(f"⏱ {esc(exc)}")
        return
    except GeminiRequestError as exc:
        await callback.message.answer(f"❌ {esc(exc)}")
        return

    await state.set_state(QuizState.in_progress)
    await state.update_data(
        quiz=quiz, current_index=0, correct_count=0,
        topic_key=topic_key, topic_name=topic_name,
    )
    await send_quiz_question(callback.message, state)


async def send_quiz_question(message: Message, state: FSMContext):
    data = await state.get_data()
    quiz = data["quiz"]
    idx = data["current_index"]

    if idx >= len(quiz):
        await finish_quiz(message, state)
        return

    question = quiz[idx]
    buttons = [
        [InlineKeyboardButton(text=opt, callback_data=f"quiz_answer:{i}")]
        for i, opt in enumerate(question["options"])
    ]
    await message.answer(
        f"❓ Вопрос {idx + 1}/{len(quiz)}:\n\n{esc(question['question'])}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(QuizState.in_progress, F.data.startswith("quiz_answer:"))
async def quiz_answer(callback: CallbackQuery, state: FSMContext):
    chosen_index = int(callback.data.split(":")[1])
    data = await state.get_data()
    quiz = data["quiz"]
    idx = data["current_index"]
    question = quiz[idx]
    correct_index = question.get("correct_index", 0)

    correct_count = data["correct_count"]
    if chosen_index == correct_index:
        correct_count += 1
        feedback = "✅ Верно!"
    else:
        correct_option = question["options"][correct_index]
        feedback = f"❌ Неверно. Правильный ответ: {esc(correct_option)}"

    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(feedback)

    await state.update_data(current_index=idx + 1, correct_count=correct_count)
    await send_quiz_question(callback.message, state)


async def finish_quiz(message: Message, state: FSMContext):
    data = await state.get_data()
    quiz = data["quiz"]
    correct_count = data["correct_count"]
    topic_name = data["topic_name"]
    total = len(quiz)
    score = round(correct_count / total * 100, 1) if total else 0

    await run_db(
        save_education_progress, message.from_user.id, topic_name, 1, score,
    )

    await message.answer(
        f"🏁 Квиз по теме «{esc(topic_name)}» завершён!\n"
        f"Результат: {correct_count}/{total} ({score}%)\n\n"
        "Продолжить обучение можно командой /learn.",
    )
    await state.clear()
