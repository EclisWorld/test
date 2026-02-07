import re
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import is_owner
from app.db import db

router = Router()


def _parse_int_arg(text: str) -> int | None:
    parts = (text or "").strip().split()
    if len(parts) < 2:
        return None
    try:
        return int(parts[1])
    except Exception:
        return None


@router.message(Command("whoami"))
async def whoami(message: Message):
    if not message.from_user or not message.chat:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    manager_limit = await db.get_manager_limit(chat_id)
    is_mgr = manager_limit > 0
    is_mgr_admin = await db.is_manager_admin(chat_id, user_id)

    manager_of_this = await db.get_manager_for_child(chat_id)

    await message.reply(
        "whoami\n"
        f"- chat_id: {chat_id}\n"
        f"- user_id: {user_id}\n"
        f"- is_owner: {is_owner(user_id)}\n"
        f"- is_manager_group: {is_mgr} (limit={manager_limit})\n"
        f"- is_manager_admin: {is_mgr_admin}\n"
        f"- manager_of_this_chat: {manager_of_this}\n"
    )


@router.message(Command("limit"))
async def set_limit(message: Message):
    # فقط owner
    if not message.from_user or not is_owner(message.from_user.id):
        return

    if not message.chat:
        return

    chat_id = message.chat.id
    limit = _parse_int_arg(message.text)
    if limit is None or limit < 0:
        await message.reply("فرمت درست: /limit 10")
        return

    # این چت را به عنوان manager group ثبت کن (اگر نبود)
    await db.upsert_manager_group(chat_id, title=getattr(message.chat, "title", None))
    await db.set_manager_limit(chat_id, limit)

    await message.reply(f"limit این گروه مدیریتی تنظیم شد: {limit}")


@router.message(Command("link"))
async def link_child(message: Message):
    if not message.from_user or not message.chat:
        return

    manager_chat_id = message.chat.id
    user_id = message.from_user.id

    # فقط owner یا admin مدیر همان گروه مدیریتی
    if not (is_owner(user_id) or await db.is_manager_admin(manager_chat_id, user_id)):
        return

    child_chat_id = _parse_int_arg(message.text)
    if child_chat_id is None:
        await message.reply("فرمت درست: /link -1001234567890")
        return

    ok, msg = await db.link_child(manager_chat_id, child_chat_id)
    await message.reply(msg)


@router.message(Command("unlink"))
async def unlink_child(message: Message):
    # طبق قانون تو: حذف فقط توسط owner
    if not message.from_user or not is_owner(message.from_user.id):
        return
    if not message.chat:
        return

    child_chat_id = _parse_int_arg(message.text)
    if child_chat_id is None:
        await message.reply("فرمت درست: /unlink -1001234567890")
        return

    await db.unlink_child(child_chat_id)
    await message.reply("unlink انجام شد (اگر لینک وجود داشت حذف شد).")
