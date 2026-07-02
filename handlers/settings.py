# handlers/settings.py
"""
/settings — имя, уровень знаний, базовая валюта, часовой пояс.
/progress — прогресс обучения и статистика дневника сделок.
"""

import json
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from database import (
    update_user_field, get_education_progress, get_trades,
    get_latest_portfolio_snapshot,
)
from utils.db_async import run_db
from utils.text import esc

logger = logging.getLogger(__name__)
router = Router(name="settings")

CURRENCIES = ["USD", "EUR", "RUB"]

LEVEL_NAMES = {
    "beginner": "Новичок",
    "intermediate": "Средний",
    "advanced": "Продвинутый",
}

PROFILE_NAMES = {
    "conservative": "Консервативный",
    "moderate": "Умеренный",
    "aggressive": "Агрессивный",
}


def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎓 Изменить уровень", callback_data="settings:level")],
            [InlineKeyboardButton(text="💱 Изменить валюту", callback_data="settings:currency")],
        ]
    )


@router.message(Command("settings"))
async def cmd_settings(message: Message, db_user: dict = None):
    if not db_user:
        await message.answer("Не удалось загрузить профиль. Попробуйте /start.")
        return

    risk_label = (
        PROFILE_NAMES.get(db_user["risk_profile"], db_user["risk_profile"])
        if db_user["risk_profile"]
        else "не определён (пройдите /portfolio)"
    )

    text = (
        "⚙️ <b>Ваш профиль:</b>\n\n"
        f"Имя: {esc(db_user['name'])}\n"
        f"Уровень: {esc(LEVEL_NAMES.get(db_user['level'], db_user['level']))}\n"
        f"Базовая валюта: {esc(db_user['base_currency'])}\n"
        f"Часовой пояс: {esc(db_user['timezone'])}\n"
        f"Риск-профиль: {esc(risk_label)}\n"
    )
    await message.answer(text, reply_markup=settings_keyboard())


@router.callback_query(F.data == "settings:level")
async def change_level(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌱 Новичок", callback_data="setlevel:beginner")],
            [InlineKeyboardButton(text="📊 Средний", callback_data="setlevel:intermediate")],
            [InlineKeyboardButton(text="🚀 Продвинутый", callback_data="setlevel:advanced")],
        ]
    )
    await callback.message.edit_text("Выберите новый уровень знаний:", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("setlevel:"))
async def set_level(callback: CallbackQuery):
    level = callback.data.split(":")[1]
    await run_db(update_user_field, callback.from_user.id, "level", level)
    label = LEVEL_NAMES.get(level, level)
    await callback.message.edit_text(f"✅ Уровень обновлён: {esc(label)}")
    await callback.answer()


@router.callback_query(F.data == "settings:currency")
async def change_currency(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=c, callback_data=f"setcurrency:{c}")] for c in CURRENCIES
        ]
    )
    await callback.message.edit_text("Выберите базовую валюту:", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("setcurrency:"))
async def set_currency(callback: CallbackQuery):
    currency = callback.data.split(":")[1]
    await run_db(update_user_field, callback.from_user.id, "base_currency", currency)
    await callback.message.edit_text(f"✅ Базовая валюта обновлена: {esc(currency)}")
    await callback.answer()


@router.message(Command("progress"))
async def cmd_progress(message: Message):
    progress_rows = await run_db(get_education_progress, message.from_user.id)
    trades = await run_db(get_trades, message.from_user.id)
    snapshot = await run_db(get_latest_portfolio_snapshot, message.from_user.id)

    if progress_rows:
        completed_topics = {row["topic"] for row in progress_rows}
        avg_score = sum(row["score"] for row in progress_rows) / len(progress_rows)
        education_text = (
            f"Пройдено тем: {len(completed_topics)}\n"
            f"Средний результат квизов: {avg_score:.1f}%\n"
        )
    else:
        education_text = "Вы ещё не проходили уроки. Начните с /learn."

    trades_count = len(trades)
    journal_text = (
        f"Всего сделок в дневнике: {trades_count}" if trades_count
        else "Сделок пока нет. Добавьте первую через /trade."
    )

    portfolio_text = "Модельный портфель не создан. Пройдите /portfolio."
    if snapshot:
        data = json.loads(snapshot["allocation_json"])
        profile = PROFILE_NAMES.get(data.get("profile", ""), data.get("profile", ""))
        portfolio_text = f"Риск-профиль: {profile} (сохранён)"

    await message.answer(
        f"📊 <b>Ваш прогресс:</b>\n\n"
        f"<b>Обучение:</b>\n{esc(education_text)}\n"
        f"<b>Дневник:</b>\n{esc(journal_text)}\n"
        f"<b>Портфель:</b>\n{esc(portfolio_text)}",
    )
