import os
import logging

from aiohttp import web

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from app.config import BOT_TOKEN
from app.db import db

from app.handlers.private_panel import router as private_panel_router
from app.handlers.register_group import router as register_group_router
# اگر بعداً درستش کردی:
# from app.handlers.group_guard import router as group_guard_router


def must_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing env var: {name}")
    return v


async def on_startup(app: web.Application):
    await db.init()
    # WEBHOOK_URL باید کامل باشد (https://.../webhook)
    webhook_url = must_env("WEBHOOK_URL")
    secret = os.getenv("WEBHOOK_SECRET")  # اختیاری

    bot: Bot = app["bot"]
    await bot.set_webhook(
        url=webhook_url,
        secret_token=secret,
        drop_pending_updates=True,
    )
    logging.getLogger("eclis").info("Webhook set: %s", webhook_url)


async def on_shutdown(app: web.Application):
    bot: Bot = app["bot"]
    try:
        await bot.delete_webhook()
    except Exception:
        pass
    await bot.session.close()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    bot_token = must_env("BOT_TOKEN")
    bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    dp = Dispatcher()
    dp.include_router(private_panel_router)
    dp.include_router(register_group_router)
    # dp.include_router(group_guard_router)

    app = web.Application()
    app["bot"] = bot

    # مسیر وبهوک روی سرور
    webhook_path = os.getenv("WEBHOOK_PATH", "/webhook")

    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=webhook_path)
    setup_application(app, dp, bot=bot)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    port = int(os.getenv("PORT", "8080"))
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
