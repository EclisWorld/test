from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery

from app.config import is_owner
from app.db import db


def _get_user_id(event: Message | CallbackQuery) -> int:
    if isinstance(event, CallbackQuery):
        return int(event.from_user.id)
    return int(event.from_user.id)


class IsOwner(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        return is_owner(_get_user_id(event))


class IsAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        return await db.is_admin(_get_user_id(event))


class IsAdminOrOwner(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        uid = _get_user_id(event)
        return is_owner(uid) or await db.is_admin(uid)
