from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery

from app.config import OWNER_ID
from app.db import db


def _get_user_id(event: Message | CallbackQuery) -> int:
    # Works for both messages and callback queries
    if isinstance(event, CallbackQuery):
        return event.from_user.id
    return event.from_user.id


class IsOwner(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        return _get_user_id(event) == OWNER_ID


class IsAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        return await db.is_admin(_get_user_id(event))


class IsAdminOrOwner(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        uid = _get_user_id(event)
        return uid == OWNER_ID or await db.is_admin(uid)
