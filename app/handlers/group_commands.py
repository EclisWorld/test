# app/handlers/group_commands.py
# فرمان‌های گروهی (بدون اسلش) برای مدیریت گارد/سیف/بن
# طراحی:
# - فقط داخل group/supergroup کار می‌کند
# - دسترسی: Owner یا (Legacy Global Admin) یا Admin همان management (manager_admin)
# - scope: با resolve_effective_chat_id، اگر داخل child باشی، روی manager اعمال می‌شود
# - resolve target: reply > text_mention > @mention > عدد

from __future__ import annotations

import re
import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.enums import MessageEntityType

from app.db import db
from app.config import is_owner

router = Router()
log = logging.getLogger("eclis.groupcmd")


# -------------------------
# Target resolver
# -------------------------
async def resolve_target_user_id(message: Message) -> int | None:
    """
    priority:
    1) reply -> replied user id
    2) entities: text_mention / mention (@username)
    3) numeric in text
    4) plain @username (fallback)
    """
    # 1) reply
    if message.reply_to_message and message.reply_to_message.from_user:
        return int(message.reply_to_message.from_user.id)

    text = message.text or ""

    # 2) entities (mention / text_mention)
    if message.entities:
        for ent in message.entities:
            if ent.type == MessageEntityType.TEXT_MENTION and ent.user:
                return int(ent.user.id)

            if ent.type == MessageEntityType.MENTION:
                username = text[ent.offset: ent.offset + ent.length]  # like "@name"
                try:
                    chat = await message.bot.get_chat(username)
                    # برای یوزرنیم‌ها، chat.id همان user_id است
                    return int(chat.id)
                except Exception:
                    # اگر نتونست resolve کنه، ادامه بده
                    pass

    # 3) numeric in text
    m = re.search(r"\b(\d{5,})\b", text)
    if m:
        return int(m.group(1))

    # 4) plain @username fallback
    m = re.search(r"@([A-Za-z0-9_]{5,})", text)
    if m:
        try:
            chat = await message.bot.get_chat("@" + m.group(1))
            return int(chat.id)
        except Exception:
            return None

    return None


# -------------------------
# Context / access
# -------------------------
async def _get_effective_manager(chat_id: int) -> int:
    return int(await db.resolve_effective_chat_id(int(chat_id)))


async def _has_manage_access(user_id: int, manager_chat_id: int) -> bool:
    if is_owner(int(user_id)):
        return True

    # legacy global admin
    try:
        if await db.is_admin(int(user_id)):
            return True
    except Exception:
        pass

    # manager admin
    return await db.is_manager_admin(int(manager_chat_id), int(user_id))


async def _deny(message: Message, text: str = "دسترسی ندارید.") -> None:
    try:
        await message.reply(text)
    except Exception:
        pass


# -------------------------
# Guard ON/OFF (بدون اسلش)
# -------------------------
@router.message(F.chat.type.in_({"group", "supergroup"}) & F.text.regexp(r"^(on|off)$", flags=re.I))
async def cmd_on_off(message: Message):
    if not message.from_user:
        return

    uid = int(message.from_user.id)
    effective = await _get_effective_manager(message.chat.id)

    if not await _has_manage_access(uid, effective):
        return

    enabled = (message.text or "").strip().lower() == "on"
    await db.set_guard_enabled(effective, enabled)

    title = await db.get_manager_title(effective)
    await message.reply(f"✅ Guard برای مدیریت «{title}» شد: {'ON' if enabled else 'OFF'}")


# -------------------------
# SAFE add/remove (بدون اسلش)
# add @user | add 123 | reply + add
# remove @user | remove 123 | reply + remove
# -------------------------
@router.message(F.chat.type.in_({"group", "supergroup"}) & F.text.regexp(r"^add\b", flags=re.I))
async def cmd_add_safe(message: Message):
    if not message.from_user:
        return

    uid = int(message.from_user.id)
    effective = await _get_effective_manager(message.chat.id)

    if not await _has_manage_access(uid, effective):
        return

    target_id = await resolve_target_user_id(message)
    if not target_id:
        await message.reply("کاربر پیدا نشد. روی پیام ریپلای کن یا @username / id عددی بده.")
        return

    # اضافه به SAFE اسکوپ effective (manager)
    await db.add_safe(int(target_id), chat_id=int(effective))
    await message.reply(f"✅ {target_id} به SAFE مدیریت اضافه شد. (scope={effective})")


@router.message(F.chat.type.in_({"group", "supergroup"}) & F.text.regexp(r"^remove\b", flags=re.I))
async def cmd_remove_safe(message: Message):
    if not message.from_user:
        return

    uid = int(message.from_user.id)
    effective = await _get_effective_manager(message.chat.id)

    if not await _has_manage_access(uid, effective):
        return

    target_id = await resolve_target_user_id(message)
    if not target_id:
        await message.reply("کاربر پیدا نشد. روی پیام ریپلای کن یا @username / id عددی بده.")
        return

    # حذف از SAFE اسکوپ effective
    await db.remove_safe(int(target_id), chat_id=int(effective))
    await message.reply(f"✅ {target_id} از SAFE حذف شد. (scope={effective})")


# -------------------------
# ban/unban (فقط همین چت جاری)
# ban @user | ban 123 | reply + ban
# -------------------------
@router.message(F.chat.type.in_({"group", "supergroup"}) & F.text.regexp(r"^ban\b", flags=re.I))
async def cmd_ban_local(message: Message):
    if not message.from_user:
        return

    uid = int(message.from_user.id)
    effective = await _get_effective_manager(message.chat.id)
    if not await _has_manage_access(uid, effective):
        return

    target_id = await resolve_target_user_id(message)
    if not target_id:
        await message.reply("کاربر پیدا نشد. ریپلای یا @ یا id بده.")
        return

    try:
        await message.bot.ban_chat_member(chat_id=int(message.chat.id), user_id=int(target_id))
        await db.add_ban(int(target_id), int(message.chat.id))  # local ban
        await message.reply(f"⛔ Ban شد در همین گروه: {target_id}")
    except Exception as e:
        await message.reply(f"❌ Ban ناموفق: {e}")


@router.message(F.chat.type.in_({"group", "supergroup"}) & F.text.regexp(r"^unban\b", flags=re.I))
async def cmd_unban_local(message: Message):
    if not message.from_user:
        return

    uid = int(message.from_user.id)
    effective = await _get_effective_manager(message.chat.id)
    if not await _has_manage_access(uid, effective):
        return

    target_id = await resolve_target_user_id(message)
    if not target_id:
        await message.reply("کاربر پیدا نشد. ریپلای یا @ یا id بده.")
        return

    try:
        await message.bot.unban_chat_member(
            chat_id=int(message.chat.id),
            user_id=int(target_id),
            only_if_banned=True,
        )
        await db.remove_ban(int(target_id), int(message.chat.id))
        await message.reply(f"✅ Unban شد در همین گروه: {target_id}")
    except Exception as e:
        await message.reply(f"❌ Unban ناموفق: {e}")


# -------------------------
# gban/gunban (کل management + زیرمجموعه‌ها)
# نکته: نیازمند متد db.get_scope_chats_for_manager(mid)
# که باید [mid] + تمام childهایش را برگرداند.
# -------------------------
@router.message(F.chat.type.in_({"group", "supergroup"}) & F.text.regexp(r"^gban\b", flags=re.I))
async def cmd_gban(message: Message):
    if not message.from_user:
        return

    uid = int(message.from_user.id)
    effective = await _get_effective_manager(message.chat.id)
    if not await _has_manage_access(uid, effective):
        return

    target_id = await resolve_target_user_id(message)
    if not target_id:
        await message.reply("کاربر پیدا نشد. ریپلای کن یا mention کن یا id عددی بده.")
        return

    # scope chats (manager + children)
    try:
        chats = await db.get_scope_chats_for_manager(int(effective))
    except Exception:
        await message.reply("❌ DB: متد get_scope_chats_for_manager وجود ندارد یا خطا داد.")
        return

    ok, fail = 0, 0
    last_err = None

    for cid in chats:
        try:
            await message.bot.ban_chat_member(chat_id=int(cid), user_id=int(target_id))
            await db.add_ban(int(target_id), int(cid))
            ok += 1
        except Exception as e:
            fail += 1
            last_err = str(e)

    await message.reply(
        f"⛔ GBAN scope={len(chats)} ok={ok} fail={fail}"
        + (f"\nآخرین خطا: {last_err}" if last_err else "")
    )


@router.message(F.chat.type.in_({"group", "supergroup"}) & F.text.regexp(r"^gunban\b", flags=re.I))
async def cmd_gunban(message: Message):
    if not message.from_user:
        return

    uid = int(message.from_user.id)
    effective = await _get_effective_manager(message.chat.id)
    if not await _has_manage_access(uid, effective):
        return

    target_id = await resolve_target_user_id(message)
    if not target_id:
        await message.reply("کاربر پیدا نشد. ریپلای کن یا mention کن یا id عددی بده.")
        return

    try:
        chats = await db.get_scope_chats_for_manager(int(effective))
    except Exception:
        await message.reply("❌ DB: متد get_scope_chats_for_manager وجود ندارد یا خطا داد.")
        return

    ok, fail = 0, 0
    last_err = None

    for cid in chats:
        try:
            await message.bot.unban_chat_member(
                chat_id=int(cid),
                user_id=int(target_id),
                only_if_banned=True,
            )
            await db.remove_ban(int(target_id), int(cid))
            ok += 1
        except Exception as e:
            fail += 1
            last_err = str(e)

    await message.reply(
        f"✅ GUNBAN scope={len(chats)} ok={ok} fail={fail}"
        + (f"\nآخرین خطا: {last_err}" if last_err else "")
    )
