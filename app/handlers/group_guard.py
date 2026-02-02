from aiogram import Router
from aiogram.types import ChatMemberUpdated

from app.db import db
from app.config import OWNER_ID

router = Router()


@router.chat_member()
async def guard_new_members(event: ChatMemberUpdated):
    """
    Triggered on any chat member update.
    We only care about NEW joins.
    """

    if event.new_chat_member.status != "member":
        return

    user = event.from_user
    chat = event.chat

    # Save group info (once)
    await db.add_group(chat.id, chat.title)

    # Allow owner always
    if user.id == OWNER_ID:
        return

    # Check SAFE list
    if await db.is_safe(user.id):
        return

    # Ban user from THIS group only
    try:
        await event.bot.ban_chat_member(
            chat_id=chat.id,
            user_id=user.id
        )
    except Exception:
        pass

    # Save ban
    await db.add_ban(user.id, chat.id)

    # Send log to owner
    try:
        await event.bot.send_message(
            OWNER_ID,
            f"این کاربر با این ID بن شد : {user.id}\nECLIS HAMISHE SAFE <3"
        )
    except Exception:
        pass
