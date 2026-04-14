import asyncio

from contextlib import suppress
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import GIVEAWAYS_BOT_TOKEN, REMINDERS_ENABLED
from src.bot.handlers import admin_router, user_router
from src.bot.reminders import run_reminders

bot = Bot(GIVEAWAYS_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
dp.include_router(admin_router)
dp.include_router(user_router)


async def run_bot():
    await bot.delete_webhook(False)
    reminder_task = asyncio.create_task(run_reminders(bot)) if REMINDERS_ENABLED else None
    try: await dp.start_polling(bot)
    finally:
        if reminder_task is None: return
        reminder_task.cancel()
        with suppress(asyncio.CancelledError): await reminder_task
