# app/handlers/register_group.py
from aiogram import Router
from aiogram.types import ChatMemberUpdated

from app.db import db

router = Router()

@router.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated):
    """
    ثبت/آپدیت گروه یا کانال وقتی بات اضافه/حذف/ادمین می‌شود.
    این event مستقل از privacy است و برای register کردن بهترین گزینه است.
    """
    chat = event.chat
    # chat.type: "private" | "group" | "supergroup" | "channel"
    if chat.type not in ("group", "supergroup", "channel"):
        return

    title = getattr(chat, "title", None)
    await db.upsert_group(chat_id=chat.id, title=title, chat_type=chat.type)
