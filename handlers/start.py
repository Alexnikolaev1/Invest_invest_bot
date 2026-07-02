# handlers/start.py
"""Команда /start — приветствие, регистрация пользователя, выбор уровня знаний."""

import logging

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from config import DISCLAIMER
from utils.db_async import run_db
from database import update_user_field
from utils.keyboards import MAIN_MENU

logger = logging.getLogger(__name__)
router = Router(name="start")


def level_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌱 Новичок", callback_data="level:beginner")],
            [InlineKeyboardButton(text="📊 Средний", callback_data="level:intermediate")],
            [InlineKeyboardButton(text="🚀 Продвинутый", callback_data="level:advanced")],
        ]
    )


@router.message(CommandStart())
async def cmd_start(message: Message):
    welcome_text = (
        "👋 Добро пожаловать в <b>INVESTMIND AI</b>!\n\n"
        "Я — ваш персональный AI-наставник по инвестициям. Помогу разобраться "
        "с фондовым рынком и криптовалютами, проанализирую акции и активы, "
        "соберу для вас сводку новостей, помогу построить модельный портфель "
        "и вести дневник сделок.\n\n"
        f"{DISCLAIMER}\n\n"
        "Для начала расскажите, какой у вас уровень знаний в инвестициях?"
    )
    await message.answer(welcome_text, reply_markup=level_keyboard())


@router.callback_query(F.data.startswith("level:"))
async def process_level_choice(callback: CallbackQuery):
    level = callback.data.split(":")[1]
    await run_db(update_user_field, callback.from_user.id, "level", level)

    level_names = {
        "beginner": "Новичок",
        "intermediate": "Средний",
        "advanced": "Продвинутый",
    }
    await callback.message.edit_text(
        f"✅ Отлично! Ваш уровень: <b>{level_names.get(level, level)}</b>.\n\n"
        "Теперь вы можете пользоваться главным меню ниже или командами:\n"
        "/learn — обучение\n"
        "/analyse &lt;тикер&gt; — анализ акции/крипты\n"
        "/news &lt;тикер или тема&gt; — новости\n"
        "/portfolio — модельный портфель\n"
        "/trade и /journal — дневник сделок\n"
        "/settings — настройки профиля",
    )
    await callback.message.answer("Главное меню:", reply_markup=MAIN_MENU)
    await callback.answer()


@router.message(F.text == "📈 Анализ")
async def menu_analyse_hint(message: Message):
    await message.answer(
        "Введите команду в формате:\n<code>/analyse AAPL</code> или <code>/analyse BTC</code>",
    )


@router.message(F.text == "📰 Новости")
async def menu_news_hint(message: Message):
    await message.answer(
        "Введите команду в формате:\n<code>/news Tesla</code> или <code>/news нефть</code>",
    )


@router.message(F.text == "📚 Обучение")
async def menu_learn_hint(message: Message):
    from handlers.learn import show_topics
    await show_topics(message)


@router.message(F.text == "📋 Портфель")
async def menu_portfolio_hint(message: Message, state: FSMContext):
    from handlers.portfolio import cmd_portfolio
    await cmd_portfolio(message, state)


@router.message(F.text == "📝 Дневник")
async def menu_journal_hint(message: Message):
    from handlers.journal import cmd_journal
    await cmd_journal(message)


@router.message(F.text == "⚙️ Профиль")
async def menu_settings_hint(message: Message):
    from handlers.settings import cmd_settings
    await cmd_settings(message)
