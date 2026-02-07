# app/main.py
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from app.config import BOT_TOKEN
from app.db import db

from app.handlers.start import router as start_router
from app.handlers.private_panel import router as private_panel_router
from app.handlers.owner_mainpanel import router as owner_mainpanel_router
from app.handlers.group_commands import router as group_commands_router
from app.handlers.manager_ops import router as manager_ops_router
from app.handlers.register_group import router as register_group_router
from app.handlers.group_guard import router as group_guard_router
from app.handlers.manager_group import router as manager_group_router
from app.handlers.hub_commands import router as hub_commands_router



async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    logger = logging.getLogger("eclis")

    await db.init()

    proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    session = AiohttpSession(proxy=proxy) if proxy else AiohttpSession()

    bot = Bot(
        token=BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    from aiogram.fsm.storage.memory import MemoryStorage

    dp = Dispatcher(storage=MemoryStorage())


    dp.include_router(start_router)
    dp.include_router(private_panel_router)
    dp.include_router(owner_mainpanel_router)

    dp.include_router(manager_ops_router)
    dp.include_router(manager_group_router)

    dp.include_router(register_group_router)
    dp.include_router(group_guard_router)

    dp.include_router(group_commands_router)
    dp.include_router(hub_commands_router)




    try:
        try:
            await bot.delete_webhook(drop_pending_updates=True)
        except Exception as e:
            logger.warning("delete_webhook failed (ignored): %s", e)

        logger.info("ECLIS Guard Bot started (polling)")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
