# app/handlers/manager_ops.py
import re
import logging
from aiogram import Router, F
from aiogram.types import Message

from app.db import db
from app.config import is_owner

router = Router()
log = logging.getLogger("eclis.manager_ops")


async def _has_access(message: Message) -> bool:
    if not message.from_user:
        return False
    uid = int(message.from_user.id)

    # Owner همیشه
    if is_owner(uid):
        return True

    # اگر ادمین تلگرام گروه هست (پیشنهادی)، یا سیستم DB خودت:
    try:
        member = await message.bot.get_chat_member(message.chat.id, uid)
        if member.status in ("administrator", "creator"):
            return True
    except Exception:
        pass

    # fallback: legacy global admins
    try:
        if await db.is_admin(uid):
            return True
    except Exception:
        pass

    return False


@router.message(F.chat.type.in_({"group", "supergroup"}) & F.text.regexp(r"^\s*eclis\s+(on|off)\s*$", flags=re.I))
async def eclis_hub_toggle(message: Message):
    if not await _has_access(message):
        # اینجا می‌تونی silent هم بذاری، ولی برای دیباگ بهتره جواب بده
        await message.reply("دسترسی ندارید.")
        return

    cmd = (message.text or "").strip().lower()
    mode = "on" if " on" in cmd else "off"

    # ثبت گروه در DB (اختیاری ولی خوبه)
    try:
        await db.upsert_group(chat_id=message.chat.id, title=getattr(message.chat, "title", None), chat_type=message.chat.type)
    except Exception:
        pass

    if mode == "on":
        ok, msg = await db.set_global_hub(message.chat.id)
        # اگر HUB فعال شد، guard همین مدیریت را هم روشن کن (طبق خواسته‌ی تو)
        if ok:
            # HUB روی خود این گروه است، پس effective هم همین است
            await db.set_guard_enabled(message.chat.id, True)

        hub = await db.get_global_hub()
        await message.reply(f"{msg}\n\nHUB فعلی: {hub}")
        log.info("HUB ON by=%s chat=%s ok=%s hub=%s", message.from_user.id, message.chat.id, ok, hub)
        return

    # off
    ok, msg = await db.disable_global_hub(message.chat.id)
    if ok:
        await db.set_guard_enabled(message.chat.id, False)

    hub = await db.get_global_hub()
    await message.reply(f"{msg}\n\nHUB فعلی: {hub}")
    log.info("HUB OFF by=%s chat=%s ok=%s hub=%s", message.from_user.id, message.chat.id, ok, hub)
