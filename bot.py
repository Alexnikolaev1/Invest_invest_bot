# bot.py
"""
Точка входа INVESTMIND AI.
Запускает бота в режиме вебхука (на Railway), либо в режиме поллинга (локально),
в зависимости от наличия переменной окружения WEBHOOK_URL / RAILWAY_STATIC_URL.
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from config import (
    TELEGRAM_BOT_TOKEN, WEBHOOK_URL, WEBHOOK_PATH, PORT, USE_WEBHOOK, LOG_LEVEL,
)
from database import init_db
from handlers import all_routers
from middlewares import UserRegistrationMiddleware

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.middleware(UserRegistrationMiddleware())
    for router in all_routers:
        dp.include_router(router)
    return dp


async def on_startup_webhook(bot: Bot):
    full_webhook_url = WEBHOOK_URL.rstrip("/") + WEBHOOK_PATH
    await bot.set_webhook(full_webhook_url, drop_pending_updates=True)
    logger.info("Вебхук установлен: %s", full_webhook_url)


async def on_shutdown(bot: Bot):
    await bot.session.close()
    logger.info("Бот остановлен.")


async def run_polling(bot: Bot, dp: Dispatcher):
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Бот запущен в режиме поллинга.")
    try:
        await dp.start_polling(bot)
    finally:
        await on_shutdown(bot)


def run_webhook(bot: Bot, dp: Dispatcher):
    app = web.Application()

    dp.startup.register(on_startup_webhook)
    dp.shutdown.register(on_shutdown)

    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    logger.info("Бот запускается в режиме вебхука на порту %s.", PORT)
    web.run_app(app, host="0.0.0.0", port=PORT)


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в переменных окружения.")

    init_db()

    bot = Bot(
        token=TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = create_dispatcher()

    if USE_WEBHOOK:
        run_webhook(bot, dp)
    else:
        asyncio.run(run_polling(bot, dp))


if __name__ == "__main__":
    main()
