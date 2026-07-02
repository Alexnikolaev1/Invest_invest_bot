# utils/keyboards.py
"""Общие клавиатуры, используемые в разных хендлерах."""

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📈 Анализ"), KeyboardButton(text="📰 Новости")],
        [KeyboardButton(text="📚 Обучение"), KeyboardButton(text="📋 Портфель")],
        [KeyboardButton(text="📝 Дневник"), KeyboardButton(text="⚙️ Профиль")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите раздел или введите команду",
)
