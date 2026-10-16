import asyncio
import hashlib
import logging
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hr_attendance_project.settings")

import django

django.setup()

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisEventIsolation, RedisStorage
from django.conf import settings

from bot.config import BOT_TOKEN
from bot.handlers import router
from bot.lease import RedisLease


logger = logging.getLogger("attendance")


async def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не найден в key.env")

    storage = RedisStorage.from_url(settings.REDIS_URL)
    isolation = RedisEventIsolation.from_url(settings.REDIS_URL)
    dp = Dispatcher(storage=storage, events_isolation=isolation)
    dp.include_router(router)
    bot = Bot(token=BOT_TOKEN)

    # The token itself is never placed in Redis or logs.
    token_fingerprint = hashlib.sha256(BOT_TOKEN.encode("utf-8")).hexdigest()[:16]
    lease = RedisLease(
        settings.REDIS_URL,
        key=f"attendance:bot:polling-lease:{token_fingerprint}",
    )
    if not await lease.acquire():
        await bot.session.close()
        await storage.close()
        await isolation.close()
        await lease.redis.aclose()
        raise RuntimeError("Другой экземпляр бота уже владеет polling lease")

    renewal = asyncio.create_task(lease.keep_alive(dp.stop_polling))
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("bot_polling_started", extra={"event": "bot_polling_started"})
        await dp.start_polling(bot, handle_as_tasks=True, tasks_concurrency_limit=100)
    finally:
        renewal.cancel()
        await asyncio.gather(renewal, return_exceptions=True)
        await lease.release()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
