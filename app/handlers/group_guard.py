import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.types import ChatMemberUpdated

from app.db import db
from app.config import is_owner

router = Router()
log = logging.getLogger("eclis.guard")

NY = ZoneInfo("America/New_York")


@router.chat_member()
async def guard_new_members(event: ChatMemberUpdated):
    chat = event.chat
    if chat.type not in ("group", "supergroup"):
        return

    old_status = getattr(event.old_chat_member, "status", None)
    new_status = getattr(event.new_chat_member, "status", None)

    # join واقعی
    if new_status != "member":
        return
    if old_status not in ("left", "kicked"):
        return

    user = event.new_chat_member.user

    # ثبت گروه
    await db.upsert_group(chat_id=chat.id, title=getattr(chat, "title", None), chat_type=chat.type)

    # owner هیچوقت بن نشود
    if is_owner(user.id):
        return

    # effective manager برای این چت
    effective = await db.resolve_effective_chat_id(chat.id)

    # اگر گارد برای این management خاموش است -> هیچ
    if not await db.is_guard_enabled(effective):
        return

    # ✅ Safe check (global یا scoped)
    if await db.is_safe(user.id, chat_id=effective):
        return

    # بن در همین گروه
    ban_err = None
    try:
        await event.bot.ban_chat_member(chat_id=chat.id, user_id=user.id)
        await db.add_ban(user.id, chat.id)
        log.info("Banned user=%s in chat=%s effective=%s", user.id, chat.id, effective)
    except Exception as e:
        ban_err = str(e)
        log.exception("Ban failed user=%s chat=%s err=%s", user.id, chat.id, e)

    # ارسال لاگ به HUB (نه PV اونر)
    try:
        hub_id = await db.get_hub_chat_id()  # باید در db داشته باشی
        if not hub_id:
            return

        mg_title = await db.get_manager_title(effective)
        child_title = await db.get_group_title(chat.id)

        now = datetime.now(timezone.utc).astimezone(NY).strftime("%Y-%m-%d %H:%M:%S %Z")

        username = f"@{user.username}" if getattr(user, "username", None) else "-"

        text = (
            "🚫 Join Blocked\n\n"
            f"Attacker : {user.full_name}\n"
            f"Management : {mg_title} ({effective})\n"
            f"Time : {now}\n"
            f"Child : {child_title} ({chat.id})\n"
            f"Id number : {user.id}\n"
            f"Username : {username}\n"
        )
        if ban_err:
            text += f"\nBan error : {ban_err}\n"

        await event.bot.send_message(int(hub_id), text)
    except Exception:
        pass
