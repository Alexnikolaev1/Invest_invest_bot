# database.py
"""
Инициализация и утилиты для работы с базой данных SQLite.
Используем модуль sqlite3 в синхронном режиме, но все вызовы из хендлеров
оборачиваются в run_in_executor, чтобы не блокировать event loop aiogram.
"""

import sqlite3
import logging
from contextlib import contextmanager

from config import DB_PATH

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    name TEXT,
    level TEXT DEFAULT 'beginner',
    base_currency TEXT DEFAULT 'USD',
    timezone TEXT DEFAULT 'Europe/Moscow',
    risk_profile TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS education_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    topic TEXT,
    completed INTEGER DEFAULT 0,
    score REAL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analysis_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    ticker TEXT,
    response TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    type TEXT CHECK(type IN ('BUY','SELL')),
    ticker TEXT,
    quantity REAL,
    price REAL,
    date TEXT DEFAULT (DATE('now')),
    FOREIGN KEY(user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    allocation_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    data TEXT,
    expires_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS counters (
    service TEXT PRIMARY KEY,
    daily_count INTEGER DEFAULT 0,
    date TEXT DEFAULT (DATE('now'))
);
"""


def init_db() -> None:
    """Создаёт таблицы, если их ещё нет. Вызывается один раз при старте бота."""
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        conn.commit()
    logger.info("База данных инициализирована: %s", DB_PATH)


@contextmanager
def get_connection():
    """Контекстный менеджер соединения с БД (row_factory -> dict-like)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ---------- Пользователи ----------

def get_or_create_user(user_id: int, name: str = "") -> sqlite3.Row:
    with get_connection() as conn:
        cur = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO users (user_id, name) VALUES (?, ?)", (user_id, name)
            )
            conn.commit()
            cur = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
        return row


def update_user_field(user_id: int, field: str, value) -> None:
    allowed = {"name", "level", "base_currency", "timezone", "risk_profile"}
    if field not in allowed:
        raise ValueError(f"Недопустимое поле для обновления: {field}")
    with get_connection() as conn:
        conn.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, user_id))
        conn.commit()


# ---------- Обучение ----------

def save_education_progress(user_id: int, topic: str, completed: int, score: float) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO education_progress (user_id, topic, completed, score) "
            "VALUES (?, ?, ?, ?)",
            (user_id, topic, completed, score),
        )
        conn.commit()


def get_education_progress(user_id: int):
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM education_progress WHERE user_id = ? ORDER BY timestamp DESC",
            (user_id,),
        )
        return cur.fetchall()


# ---------- Анализ ----------

def save_analysis_log(user_id: int, ticker: str, response: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO analysis_log (user_id, ticker, response) VALUES (?, ?, ?)",
            (user_id, ticker, response),
        )
        conn.commit()


# ---------- Сделки ----------

def add_trade(user_id: int, trade_type: str, ticker: str, quantity: float, price: float) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO trades (user_id, type, ticker, quantity, price) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, trade_type, ticker.upper(), quantity, price),
        )
        conn.commit()


def get_trades(user_id: int):
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM trades WHERE user_id = ? ORDER BY date ASC, id ASC",
            (user_id,),
        )
        return cur.fetchall()


# ---------- Портфель (риск-профиль) ----------

def save_portfolio_snapshot(user_id: int, allocation_json: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO portfolio_snapshots (user_id, allocation_json) VALUES (?, ?)",
            (user_id, allocation_json),
        )
        conn.commit()


def get_latest_portfolio_snapshot(user_id: int):
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM portfolio_snapshots WHERE user_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        )
        return cur.fetchone()


# ---------- Счётчики дневных лимитов ----------

def get_counter(service: str) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT daily_count, date FROM counters WHERE service = ?", (service,)
        )
        row = cur.fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO counters (service, daily_count) VALUES (?, 0)", (service,)
            )
            conn.commit()
            return 0
        # Если наступил новый день - сбрасываем счётчик
        cur2 = conn.execute("SELECT DATE('now') as today")
        today = cur2.fetchone()["today"]
        if row["date"] != today:
            conn.execute(
                "UPDATE counters SET daily_count = 0, date = ? WHERE service = ?",
                (today, service),
            )
            conn.commit()
            return 0
        return row["daily_count"]


def increment_counter(service: str, amount: int = 1) -> int:
    current = get_counter(service)  # гарантирует актуальность даты
    new_value = current + amount
    with get_connection() as conn:
        conn.execute(
            "UPDATE counters SET daily_count = ? WHERE service = ?",
            (new_value, service),
        )
        conn.commit()
    return new_value
