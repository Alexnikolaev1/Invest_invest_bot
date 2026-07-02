# handlers/analyse.py
"""
Команда /analyse <тикер> — экспресс-анализ акции или криптовалюты.
Получает метрики (yfinance/Alpha Vantage или CoinGecko), передаёт их в Gemini
для качественного анализа, строит график цены за год и отправляет всё пользователю.
"""

import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, BufferedInputFile, FSInputFile

from database import save_analysis_log
from services.finance_service import get_stock_data, build_price_chart, FinanceDataError
from services.crypto_service import get_crypto_data, build_crypto_chart, CryptoDataError
from services.gemini_service import ask_gemini, GeminiRateLimitExceeded, GeminiRequestError
from services.tts import text_to_speech_file, cleanup_file
from utils.helpers import is_crypto_ticker, format_number, format_currency
from utils.db_async import run_db
from utils.text import esc
from config import DISCLAIMER, TTS_MIN_LENGTH

logger = logging.getLogger(__name__)
router = Router(name="analyse")

ANALYSIS_SYSTEM_PROMPT = (
    "Ты — финансовый аналитик с CFA. Проведи экспресс-анализ компании/актива "
    "на основе предоставленных метрик. Оцени, насколько актив переоценён/недооценён "
    "относительно отрасли и исторических значений. Упрощённо оцени справедливую "
    "стоимость (можно упомянуть DCF, но без сложных расчётов). Расскажи о ключевых "
    "рисках и драйверах роста. Дай резюме для долгосрочного инвестора. "
    "НЕ давай рекомендаций «покупать/продавать», только аналитику."
)


@router.message(Command("analyse"))
async def cmd_analyse(message: Message, command: CommandObject, db_user: dict = None):
    if not command.args:
        await message.answer(
            "Использование: <code>/analyse AAPL</code> или <code>/analyse BTC</code>",
        )
        return

    ticker = command.args.strip().split()[0].upper()
    currency = (db_user["base_currency"] if db_user else None) or "USD"

    status_msg = await message.answer(f"⏳ Анализирую {esc(ticker)}...")

    is_crypto = is_crypto_ticker(ticker)
    metrics_text = ""

    try:
        if is_crypto:
            data = await get_crypto_data(ticker)
            metrics_text = (
                f"Название: {data['name']}\n"
                f"Цена: {format_currency(data['price'], currency)}\n"
                f"Капитализация: {format_number(data['market_cap'], 0)}\n"
                f"Изменение за 24ч: {data.get('change_24h')}%\n"
                f"Изменение за 7д: {data.get('change_7d')}%\n"
                f"Исторический максимум (ATH): {format_currency(data.get('ath'), currency)}\n"
                f"Объём торгов за 24ч: {format_number(data.get('volume_24h'), 0)}"
            )
        else:
            data = await get_stock_data(ticker)
            asset_currency = data.get("currency", currency)
            metrics_text = (
                f"Компания: {data['name']}\n"
                f"Цена: {format_currency(data['price'], asset_currency)}\n"
                f"P/E: {data.get('pe')}\n"
                f"P/S: {data.get('ps')}\n"
                f"EV/EBITDA: {data.get('ev_ebitda')}\n"
                f"Дивидендная доходность: {data.get('dividend_yield')}%\n"
                f"52-недельный диапазон: {data.get('week52_low')} - {data.get('week52_high')}\n"
                f"Бета: {data.get('beta')}\n"
                f"Капитализация: {format_number(data.get('market_cap'), 0)}"
            )
    except (FinanceDataError, CryptoDataError) as exc:
        await status_msg.edit_text(f"❌ {esc(exc)}")
        return

    prompt = (
        f"Актив: {ticker}\n"
        f"Тип: {'криптовалюта' if is_crypto else 'акция'}\n"
        f"Метрики:\n{metrics_text}\n\n"
        "Проведи анализ согласно своей роли."
    )

    try:
        analysis = await ask_gemini(message.from_user.id, prompt, ANALYSIS_SYSTEM_PROMPT)
    except GeminiRateLimitExceeded as exc:
        await status_msg.edit_text(f"⏱ {esc(exc)}")
        return
    except GeminiRequestError as exc:
        await status_msg.edit_text(f"❌ Ошибка AI-анализа: {esc(exc)}")
        return

    await run_db(save_analysis_log, message.from_user.id, ticker, analysis)

    full_text = (
        f"📊 <b>Анализ: {esc(ticker)}</b>\n\n"
        f"<b>Метрики:</b>\n{esc(metrics_text)}\n\n"
        f"<b>Аналитика AI:</b>\n{esc(analysis)}\n\n"
        f"{DISCLAIMER}"
    )
    await status_msg.delete()
    await message.answer(full_text)

    try:
        if is_crypto:
            chart_buf = await build_crypto_chart(ticker, days=365)
        else:
            chart_buf = await build_price_chart(ticker, period="1y")
        photo = BufferedInputFile(chart_buf.read(), filename=f"{ticker}_chart.png")
        await message.answer_photo(photo, caption=f"График цены {ticker} за год")
    except Exception as exc:
        logger.warning("Не удалось построить график для %s: %s", ticker, exc)

    if len(analysis) > TTS_MIN_LENGTH:
        try:
            audio_path = await text_to_speech_file(analysis)
            await message.answer_voice(FSInputFile(audio_path))
            cleanup_file(audio_path)
        except Exception as exc:
            logger.warning("Не удалось озвучить анализ: %s", exc)
