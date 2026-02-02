# app/main.py
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import BOT_TOKEN
from app.db import db

# routers
from app.handlers.private_panel import router as private_panel_router
from app.handlers.register_group import router as register_group_router
# اگر بعداً group_guard اضافه شد:
# from app.handlers.group_guard import router as group_guard_router


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    logger = logging.getLogger("eclis")

    # 1) init database (tables)
    await db.init()

    # 2) init bot
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # 3) dispatcher
    dp = Dispatcher()

    # 4) routers
    dp.include_router(private_panel_router)
    dp.include_router(register_group_router)
    # dp.include_router(group_guard_router)

    # 5) start polling
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("ECLIS Guard Bot started")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
