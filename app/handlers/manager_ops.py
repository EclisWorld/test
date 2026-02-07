# app/handlers/manager_ops.py
from __future__ import annotations

import re
from aiogram import Router, F
from aiogram.types import Message
from aiogram.enums import MessageEntityType

from app.config import is_owner
from app.db import db

router = Router()

# فقط این فرمان‌ها را هندل کن (که بقیه پیام‌ها/فرمان‌ها خراب نشوند)
CMD_RE = re.compile(
    r"^(?:"
    r"eclis\s+(on|off)"          # eclis on/off
    r"|on|off"                   # on/off
    r"|add\b.*"                  # add ...
    r"|remove\b.*"               # remove ...
    r"|ban\b.*"                  # ban ...
    r"|unban\b.*"                # unban ...
    r"|gban\b.*"                 # gban ...
    r"|gunban\b.*"               # gunban ...
    r")$",
    re.IGNORECASE,
)

def _norm(txt: str | None) -> str:
    return (txt or "").strip()

async def _can_manage(user_id: int, manager_chat_id: int) -> bool:
    return is_owner(user_id) or await db.is_manager_admin(manager_chat_id, user_id)

async def _effective_manager(chat_id: int) -> int:
    # اگر چت child باشد -> manager برمی‌گردد
    # اگر manager باشد -> خودش
    return await db.resolve_effective_chat_id(chat_id)

async def _resolve_user_id_from_message(message: Message) -> int | None:
    # 1) reply
    if message.reply_to_message and message.reply_to_message.from_user:
        return int(message.reply_to_message.from_user.id)

    text = message.text or ""

    # 2) entities mention / text_mention
    if message.entities:
        for ent in message.entities:
            if ent.type == MessageEntityType.TEXT_MENTION and ent.user:
                return int(ent.user.id)
            if ent.type == MessageEntityType.MENTION:
                username = text[ent.offset: ent.offset + ent.length]  # "@name"
                try:
                    chat = await message.bot.get_chat(username)
                    return int(chat.id)
                except Exception:
                    return None

    # 3) numeric
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

@router.message(F.chat.type != "private" & F.text.regexp(CMD_RE))
async def manager_text_ops(message: Message):
    if not message.from_user:
        return

    raw = _norm(message.text)
    text = raw.lower()

    uid = int(message.from_user.id)
    effective = await _effective_manager(message.chat.id)

    # دسترسی
    if not await _can_manage(uid, effective):
        return

    # -------------------------
    # HUB: eclis on/off  (اگر شما جای دیگری پیاده کرده‌اید، همین بخش را با DB خودتان هماهنگ کن)
    # -------------------------
    if text.startswith("eclis "):
        # اینجا فرض می‌کنیم متدهای hub دارید:
        # - db.get_hub_chat_id()
        # - db.set_hub_chat_id(chat_id)
        # - db.clear_hub_chat_id()
        # اگر ندارید، باید به db اضافه شوند.
        action = text.split(None, 1)[1].strip()
        if action == "on":
            current = await db.get_hub_chat_id()
            if current and int(current) != int(message.chat.id):
                await message.reply("❌ هاب قبلاً فعال شده. اول هاب قبلی را eclis off کن.")
                return
            await db.set_hub_chat_id(int(message.chat.id))
            await message.reply("✅ هاب ثبت شد.")
            return

        if action == "off":
            current = await db.get_hub_chat_id()
            if not current:
                await message.reply("ℹ️ هابی ثبت نشده.")
                return
            if int(current) != int(message.chat.id) and not is_owner(uid):
                await message.reply("❌ فقط اونر می‌تواند هاب را خاموش کند.")
                return
            await db.clear_hub_chat_id()
            await message.reply("⛔ هاب خاموش شد.")
            return

    # -------------------------
    # ON / OFF
    # -------------------------
    if text == "on":
        await db.set_guard_enabled(effective, True)
        title = await db.get_manager_title(effective)
        await message.reply(f"✅ Guard برای «{title}» روشن شد.")
        return

    if text == "off":
        await db.set_guard_enabled(effective, False)
        title = await db.get_manager_title(effective)
        await message.reply(f"⛔ Guard برای «{title}» خاموش شد.")
        return

    # -------------------------
    # ADD / REMOVE SAFE
    # -------------------------
    if text.startswith("add"):
        target_id = await _resolve_user_id_from_message(message)
        if not target_id:
            await message.reply("کاربر پیدا نشد. ریپلای کن یا @username / id عددی بده.")
            return

        await db.add_safe(int(target_id), chat_id=effective)
        await message.reply(f"✅ {target_id} به SAFE مدیریت اضافه شد.")
        return

    if text.startswith("remove"):
        target_id = await _resolve_user_id_from_message(message)
        if not target_id:
            await message.reply("کاربر پیدا نشد. ریپلای کن یا @username / id عددی بده.")
            return

        await db.remove_safe(int(target_id), chat_id=effective)

        # فول‌بن در manager + children
        children = await db.list_children(effective)
        scope = [effective] + children

        ok = 0
        fail = 0
        for cid in scope:
            try:
                await message.bot.ban_chat_member(chat_id=int(cid), user_id=int(target_id))
                await db.add_ban(int(target_id), int(cid))
                ok += 1
            except Exception:
                fail += 1

        await message.reply(f"✅ SAFE حذف شد. ⛔ FullBan انجام شد. ok={ok} fail={fail}")
        return

    # -------------------------
    # BAN / UNBAN (فقط همین گروه)
    # -------------------------
    if text.startswith("ban") and not text.startswith("gban"):
        target_id = await _resolve_user_id_from_message(message)
        if not target_id:
            await message.reply("کاربر پیدا نشد. ریپلای یا @ یا id بده.")
            return
        try:
            await message.bot.ban_chat_member(chat_id=message.chat.id, user_id=int(target_id))
            await db.add_ban(int(target_id), int(message.chat.id))
            await message.reply(f"⛔ Ban شد در همین گروه: {target_id}")
        except Exception as e:
            await message.reply(f"❌ Ban ناموفق: {e}")
        return

    if text.startswith("unban") and not text.startswith("gunban"):
        target_id = await _resolve_user_id_from_message(message)
        if not target_id:
            await message.reply("کاربر پیدا نشد. ریپلای یا @ یا id بده.")
            return
        try:
            await message.bot.unban_chat_member(chat_id=message.chat.id, user_id=int(target_id), only_if_banned=True)
            await db.remove_ban(int(target_id), int(message.chat.id))
            await message.reply(f"✅ Unban شد در همین گروه: {target_id}")
        except Exception as e:
            await message.reply(f"❌ Unban ناموفق: {e}")
        return

    # -------------------------
    # GBAN / GUNBAN (manager + children)
    # -------------------------
    if text.startswith("gban"):
        target_id = await _resolve_user_id_from_message(message)
        if not target_id:
            await message.reply("کاربر پیدا نشد. ریپلای یا @ یا id بده.")
            return

        children = await db.list_children(effective)
        scope = [effective] + children

        ok = 0
        fail = 0
        last_err = None
        for cid in scope:
            try:
                await message.bot.ban_chat_member(chat_id=int(cid), user_id=int(target_id))
                await db.add_ban(int(target_id), int(cid))
                ok += 1
            except Exception as e:
                fail += 1
                last_err = str(e)

        await message.reply(
            f"⛔ GBAN scope={len(scope)} ok={ok} fail={fail}"
            + (f"\nآخرین خطا: {last_err}" if last_err else "")
        )
        return

    if text.startswith("gunban"):
        target_id = await _resolve_user_id_from_message(message)
        if not target_id:
            await message.reply("کاربر پیدا نشد. ریپلای یا @ یا id بده.")
            return

        children = await db.list_children(effective)
        scope = [effective] + children

        ok = 0
        fail = 0
        last_err = None
        for cid in scope:
            try:
                await message.bot.unban_chat_member(chat_id=int(cid), user_id=int(target_id), only_if_banned=True)
                await db.remove_ban(int(target_id), int(cid))
                ok += 1
            except Exception as e:
                fail += 1
                last_err = str(e)

        await message.reply(
            f"✅ GUNBAN scope={len(scope)} ok={ok} fail={fail}"
            + (f"\nآخرین خطا: {last_err}" if last_err else "")
        )
        return
