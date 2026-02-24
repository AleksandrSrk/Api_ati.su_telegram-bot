# main.py

import asyncio
import logging
from aiogram import Bot
from telegram_bot import bot, dp
from scheduler import start_scheduler
from config import TELEGRAM_BOT_TOKEN


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)


async def main():
    print("🚀 Запуск бота...")
    start_scheduler()
    print("✅ Планировщик запущен")
    print("✅ Бот запущен и ожидает сообщений")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
