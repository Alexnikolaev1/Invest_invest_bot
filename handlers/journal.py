# handlers/journal.py
"""
Дневник сделок:
/trade BUY AAPL 5 175.50 — записать сделку
/journal — показать историю, состав портфеля, P&L и диаграммы.
"""

import io
import logging
from collections import defaultdict

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, BufferedInputFile

from database import add_trade, get_trades
from services.finance_service import get_stock_data, FinanceDataError
from services.crypto_service import get_crypto_data, CryptoDataError
from services.gemini_service import ask_gemini, GeminiRateLimitExceeded, GeminiRequestError
from utils.helpers import is_crypto_ticker, format_currency, format_percent
from utils.db_async import run_db
from utils.text import esc

logger = logging.getLogger(__name__)
router = Router(name="journal")

JOURNAL_SYSTEM_PROMPT = (
    "Ты — финансовый аналитик. На основе состава портфеля клиента дай краткий (3-5 "
    "предложений) разбор рисков концентрации, диверсификации и общей структуры. "
    "Не давай рекомендаций «покупать/продавать»."
)


@router.message(Command("trade"))
async def cmd_trade(message: Message, command: CommandObject, db_user: dict = None):
    if not command.args:
        await message.answer(
            "Использование: <code>/trade BUY AAPL 5 175.50</code> "
            "или <code>/trade SELL TSLA 2 250.00</code>",
        )
        return

    parts = command.args.strip().split()
    if len(parts) != 4:
        await message.answer(
            "Неверный формат. Пример: <code>/trade BUY AAPL 5 175.50</code>",
        )
        return

    trade_type, ticker, qty_str, price_str = parts
    trade_type = trade_type.upper()
    if trade_type not in ("BUY", "SELL"):
        await message.answer("Тип сделки должен быть BUY или SELL.")
        return

    try:
        quantity = float(qty_str)
        price = float(price_str)
    except ValueError:
        await message.answer("Количество и цена должны быть числами.")
        return

    currency = (db_user["base_currency"] if db_user else None) or "USD"
    await run_db(add_trade, message.from_user.id, trade_type, ticker, quantity, price)

    await message.answer(
        f"✅ Сделка записана: {trade_type} {quantity} {ticker.upper()} "
        f"по {format_currency(price, currency)}",
    )


def _compute_positions(trades) -> dict:
    """
    Вычисляет текущие позиции (тикер -> {quantity, cost_basis}) методом средней цены.
    """
    positions = defaultdict(lambda: {"quantity": 0.0, "cost_basis": 0.0})
    for t in trades:
        pos = positions[t["ticker"]]
        if t["type"] == "BUY":
            pos["cost_basis"] += t["quantity"] * t["price"]
            pos["quantity"] += t["quantity"]
        else:
            if pos["quantity"] > 0:
                avg_price = pos["cost_basis"] / pos["quantity"]
                pos["cost_basis"] -= avg_price * t["quantity"]
            pos["quantity"] -= t["quantity"]
    return {k: v for k, v in positions.items() if v["quantity"] > 1e-9}


async def _get_current_price(ticker: str) -> float | None:
    try:
        if is_crypto_ticker(ticker):
            data = await get_crypto_data(ticker)
        else:
            data = await get_stock_data(ticker)
        return data["price"]
    except (FinanceDataError, CryptoDataError):
        return None


@router.message(Command("journal"))
async def cmd_journal(message: Message, db_user: dict = None):
    currency = (db_user["base_currency"] if db_user else None) or "USD"
    trades = await run_db(get_trades, message.from_user.id)

    if not trades:
        await message.answer(
            "У вас пока нет сделок. Добавьте первую: <code>/trade BUY AAPL 5 175.50</code>",
        )
        return

    positions = _compute_positions(trades)

    if not positions:
        await message.answer("Все позиции закрыты. История сделок пуста для отображения портфеля.")
        return

    status_msg = await message.answer("⏳ Считаю текущую стоимость портфеля...")

    total_value = 0.0
    total_cost = 0.0
    lines = []
    allocation = {}
    cost_vs_value = {}

    for ticker, pos in positions.items():
        avg_price = pos["cost_basis"] / pos["quantity"] if pos["quantity"] else 0
        current_price = await _get_current_price(ticker)
        if current_price is None:
            lines.append(f"• {esc(ticker)}: {pos['quantity']:.4f} шт. (цена недоступна)")
            continue

        value = current_price * pos["quantity"]
        pnl = value - pos["cost_basis"]
        pnl_pct = (pnl / pos["cost_basis"] * 100) if pos["cost_basis"] else 0

        total_value += value
        total_cost += pos["cost_basis"]
        allocation[ticker] = value
        cost_vs_value[ticker] = {"cost": pos["cost_basis"], "value": value}

        lines.append(
            f"• <b>{esc(ticker)}</b>: {pos['quantity']:.4f} шт. "
            f"по средней {format_currency(avg_price, currency)}\n"
            f"  Текущая цена: {format_currency(current_price, currency)} | "
            f"Стоимость: {format_currency(value, currency)} | "
            f"P&amp;L: {format_currency(pnl, currency)} ({format_percent(pnl_pct)})"
        )

    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else 0

    summary = (
        "📝 <b>Ваш портфель:</b>\n\n" + "\n\n".join(lines) +
        f"\n\n💰 <b>Общая стоимость:</b> {format_currency(total_value, currency)}\n"
        f"📈 <b>Общий P&amp;L:</b> {format_currency(total_pnl, currency)} "
        f"({format_percent(total_pnl_pct)})"
    )

    await status_msg.delete()
    await message.answer(summary)

    if allocation:
        try:
            chart_buf = _build_allocation_pie(allocation)
            photo = BufferedInputFile(chart_buf.read(), filename="allocation.png")
            await message.answer_photo(photo, caption="Распределение активов в портфеле")
        except Exception as exc:
            logger.warning("Не удалось построить круговую диаграмму: %s", exc)

        try:
            bar_buf = _build_cost_vs_value_chart(cost_vs_value)
            photo = BufferedInputFile(bar_buf.read(), filename="cost_vs_value.png")
            await message.answer_photo(photo, caption="Себестоимость vs текущая стоимость")
        except Exception as exc:
            logger.warning("Не удалось построить столбчатую диаграмму: %s", exc)

    try:
        allocation_text = ", ".join(
            f"{t}: {v / total_value * 100:.1f}%" for t, v in allocation.items()
        )
        review = await ask_gemini(
            message.from_user.id,
            f"Состав портфеля клиента: {allocation_text}",
            JOURNAL_SYSTEM_PROMPT,
        )
        await message.answer(f"🧠 <b>AI-разбор портфеля:</b>\n{esc(review)}")
    except GeminiRateLimitExceeded as exc:
        await message.answer(f"⏱ {esc(exc)}")
    except GeminiRequestError:
        pass


def _build_allocation_pie(allocation: dict) -> io.BytesIO:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = list(allocation.keys())
    values = list(allocation.values())

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=90)
    ax.set_title("Распределение активов")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def _build_cost_vs_value_chart(cost_vs_value: dict) -> io.BytesIO:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    tickers = list(cost_vs_value.keys())
    costs = [cost_vs_value[t]["cost"] for t in tickers]
    values = [cost_vs_value[t]["value"] for t in tickers]

    x = np.arange(len(tickers))
    width = 0.35

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(x - width / 2, costs, width, label="Себестоимость", color="#2b7de9")
    ax.bar(x + width / 2, values, width, label="Текущая стоимость", color="#e9902b")
    ax.set_xticks(x)
    ax.set_xticklabels(tickers)
    ax.set_title("Себестоимость vs текущая стоимость")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf
