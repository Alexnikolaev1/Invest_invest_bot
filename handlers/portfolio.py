# handlers/portfolio.py
"""
Команда /portfolio — тест на толерантность к риску и генерация модельного портфеля.
Вопросы берутся из data/risk_questions.json.
"""

import json
import logging
import os

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from database import update_user_field, save_portfolio_snapshot, get_latest_portfolio_snapshot
from services.gemini_service import ask_gemini, GeminiRateLimitExceeded, GeminiRequestError
from utils.db_async import run_db
from utils.text import esc

logger = logging.getLogger(__name__)
router = Router(name="portfolio")

QUESTIONS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "risk_questions.json")

with open(QUESTIONS_PATH, "r", encoding="utf-8") as f:
    RISK_QUESTIONS = json.load(f)

PORTFOLIO_SYSTEM_PROMPT = (
    "Ты — финансовый консультант с CFA. На основе риск-профиля клиента предложи "
    "рекомендованную аллокацию активов (акции/облигации/криптовалюта/кэш) в процентах, "
    "затем приведи 4-6 конкретных примеров ETF и/или акций с тикерами, объяснив кратко, "
    "почему они подходят под этот профиль. Не давай прямых указаний «купить/продать», "
    "только образовательные примеры для ознакомления."
)

PROFILE_NAMES = {
    "conservative": "Консервативный",
    "moderate": "Умеренный",
    "aggressive": "Агрессивный",
}


class RiskTestState(StatesGroup):
    in_progress = State()


def question_keyboard(question: dict) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=opt["text"], callback_data=f"risk_answer:{i}")]
        for i, opt in enumerate(question["options"])
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def score_to_profile(total_score: int, num_questions: int) -> str:
    max_score = num_questions * 4
    ratio = total_score / max_score
    if ratio < 0.45:
        return "conservative"
    if ratio < 0.75:
        return "moderate"
    return "aggressive"


async def _start_risk_test(message: Message, state: FSMContext):
    await message.answer(
        "📋 Для построения модельного портфеля пройдём короткий тест "
        f"на риск-профиль ({len(RISK_QUESTIONS)} вопросов)."
    )
    await state.set_state(RiskTestState.in_progress)
    await state.update_data(current_index=0, total_score=0)
    await send_risk_question(message, state)


@router.message(Command("portfolio"))
async def cmd_portfolio(message: Message, state: FSMContext):
    user_id = message.from_user.id
    snapshot = await run_db(get_latest_portfolio_snapshot, user_id)

    if snapshot:
        data = json.loads(snapshot["allocation_json"])
        profile = data.get("profile", "")
        profile_label = PROFILE_NAMES.get(profile, profile)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Пройти тест заново", callback_data="portfolio_retake")],
            ]
        )
        await message.answer(
            f"📋 У вас уже есть сохранённый портфель "
            f"(<b>{esc(profile_label)}</b>).\n\n"
            f"{esc(data.get('text', ''))}",
            reply_markup=kb,
        )
        return

    await _start_risk_test(message, state)


@router.callback_query(F.data == "portfolio_retake")
async def portfolio_retake(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await _start_risk_test(callback.message, state)


async def send_risk_question(message: Message, state: FSMContext):
    data = await state.get_data()
    idx = data["current_index"]

    if idx >= len(RISK_QUESTIONS):
        await finish_risk_test(message, state)
        return

    question = RISK_QUESTIONS[idx]
    await message.answer(
        f"❓ Вопрос {idx + 1}/{len(RISK_QUESTIONS)}:\n\n{esc(question['question'])}",
        reply_markup=question_keyboard(question),
    )


@router.callback_query(RiskTestState.in_progress, F.data.startswith("risk_answer:"))
async def risk_answer(callback: CallbackQuery, state: FSMContext):
    chosen_index = int(callback.data.split(":")[1])
    data = await state.get_data()
    idx = data["current_index"]
    question = RISK_QUESTIONS[idx]
    score = question["options"][chosen_index]["score"]

    total_score = data["total_score"] + score

    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)

    await state.update_data(current_index=idx + 1, total_score=total_score)
    await send_risk_question(callback.message, state)


async def finish_risk_test(message: Message, state: FSMContext):
    data = await state.get_data()
    total_score = data["total_score"]
    profile = score_to_profile(total_score, len(RISK_QUESTIONS))
    user_id = message.from_user.id

    await run_db(update_user_field, user_id, "risk_profile", profile)

    await message.answer(
        f"✅ Ваш риск-профиль: <b>{PROFILE_NAMES[profile]}</b>\n\n"
        "⏳ Генерирую рекомендованный портфель...",
    )

    prompt = f"Риск-профиль клиента: {PROFILE_NAMES[profile]} ({profile})."
    try:
        allocation_text = await ask_gemini(user_id, prompt, PORTFOLIO_SYSTEM_PROMPT)
    except GeminiRateLimitExceeded as exc:
        await message.answer(f"⏱ {esc(exc)}")
        await state.clear()
        return
    except GeminiRequestError as exc:
        await message.answer(f"❌ Ошибка при генерации портфеля: {esc(exc)}")
        await state.clear()
        return

    allocation_json = json.dumps(
        {"profile": profile, "text": allocation_text}, ensure_ascii=False,
    )
    await run_db(save_portfolio_snapshot, user_id, allocation_json)

    await message.answer(
        f"📋 <b>Рекомендованный портфель ({PROFILE_NAMES[profile]}):</b>\n\n"
        f"{esc(allocation_text)}",
    )
    await state.clear()
