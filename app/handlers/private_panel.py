# app/handlers/private_panel.py
from __future__ import annotations

import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo


from app.keyboards import owner_panel, admin_panel, owner_manage_submenu, owner_manage_admins_menu, owner_manage_mgmt_menu
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import MessageEntityType
from aiogram.exceptions import TelegramForbiddenError


from app.db import db
from app.config import is_owner
from app.keyboards import owner_panel, admin_panel

router = Router()
log = logging.getLogger("eclis.panel")

TZ = ZoneInfo("Europe/Berlin")

# -----------------------------
# FSM keys / states (string based)
# -----------------------------
ST_WAIT_INPUT = "panel:wait_input"

# state.data keys:
# active_chat_id: int (manager/effective)
# panel_role: "owner"|"admin"
# nav_stack: list[dict]  (simple back stack)
#
# pending:
#   op: str  ("add_admin_global"|"add_admin_manager"|"add_safe"|"remove_safe"|
#            "ban_one"|"unban_one"|"gban"|"gunban"|
#            "link_manager"|"link_child_one"|"link_children_all")
#   origin_chat_id: int (where user should send input)
#   target_chat_id: int|None (child chat selected for ban_one/unban_one/link_child_one)
#   scope_manager_id: int (effective)
#   extra: dict


# -----------------------------
# helpers
# -----------------------------
def _is_group(chat_type: str | None) -> bool:
    return chat_type in ("group", "supergroup")


def _is_numeric(s: str | None) -> bool:
    return bool(s) and s.strip().isdigit()


async def _safe_answer(cb: CallbackQuery, text: str = "", show_alert: bool = False) -> None:
    try:
        await cb.answer(text, show_alert=show_alert)
    except Exception:
        pass


async def _get_me_id(bot) -> int:
    try:
        me = await bot.get_me()
        return int(me.id)
    except Exception:
        # fallback (aiogram usually has bot.id)
        return int(getattr(bot, "id", 0) or 0)


async def _resolve_effective(chat_id: int) -> int:
    # اگر چت زیرمجموعه باشد => manager برگردانده می‌شود
    return await db.resolve_effective_chat_id(int(chat_id))


async def _has_access(uid: int, manager_id: int) -> bool:
    if is_owner(uid):
        return True
    try:
        if await db.is_admin(uid):
            return True
    except Exception:
        pass
    return await db.is_manager_admin(int(manager_id), int(uid))


async def _format_user(bot, user_id: int) -> str:
    try:
        chat = await bot.get_chat(user_id)
        name = (getattr(chat, "full_name", "") or "").strip()
        username = getattr(chat, "username", None)
        if username and name:
            return f"{user_id} | {name} (@{username})"
        if username:
            return f"{user_id} | (@{username})"
        if name:
            return f"{user_id} | {name}"
        return str(user_id)
    except Exception:
        return str(user_id)


def _push_nav(state_data: dict, payload: dict) -> dict:
    stack = list(state_data.get("nav_stack") or [])
    stack.append(payload)
    state_data["nav_stack"] = stack
    return state_data


def _pop_nav(state_data: dict) -> tuple[dict, dict | None]:
    stack = list(state_data.get("nav_stack") or [])
    if not stack:
        return state_data, None
    last = stack.pop()
    state_data["nav_stack"] = stack
    return state_data, last


def _kb_back_cancel(back_cb: str, cancel_cb: str = "cancel") -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Back", callback_data=back_cb)
    kb.button(text="❌ Cancel", callback_data=cancel_cb)
    kb.adjust(2)
    return kb

from aiogram.exceptions import TelegramForbiddenError

async def _start_input_flow(
    cb: CallbackQuery,
    state: FSMContext,
    pending: dict,
    prompt: str,
    back_cb: str = "nav:back",
) -> None:
    """
    رفتار جدید:

    - اگر کاربر داخل PV دکمه را زده: همانجا prompt را edit می‌کنیم و ورودی را همانجا می‌گیریم.
    - اگر داخل گروه/سوپرگروه زده: باز هم prompt را همانجا edit می‌کنیم (هیچ PV ارسال نمی‌کنیم).

    pending:
      - origin_user_id: فقط همین کاربر مجاز است پاسخ بدهد
      - origin_chat_id: چتی که عملیات از آن شروع شده (برای پذیرش ورودی در همان چت)
    """
    uid = int(cb.from_user.id)

    pending = dict(pending or {})
    pending["origin_user_id"] = uid
    pending["origin_chat_id"] = int(cb.message.chat.id)

    await state.set_state(ST_WAIT_INPUT)
    await state.update_data(pending=pending)

    kb = _kb_back_cancel(back_cb).as_markup()

    try:
        await cb.message.edit_text(prompt, reply_markup=kb)
    except Exception:
        await cb.message.answer(prompt, reply_markup=kb)



async def resolve_target_user_id(message: Message) -> int | None:
    """
    priority:
    1) reply -> replied user id
    2) entities: text_mention / mention
    3) numeric in text
    4) plain @username (fallback via get_chat)
    """
    # 1) reply
    if message.reply_to_message and message.reply_to_message.from_user:
        return int(message.reply_to_message.from_user.id)

    text = message.text or ""

    # 2) entities
    if message.entities:
        for ent in message.entities:
            if ent.type == MessageEntityType.TEXT_MENTION and ent.user:
                return int(ent.user.id)
            if ent.type == MessageEntityType.MENTION:
                username = text[ent.offset : ent.offset + ent.length]  # "@name"
                try:
                    chat = await message.bot.get_chat(username)
                    return int(chat.id)
                except Exception:
                    # telegram may refuse resolving unknown usernames
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


async def _render_panel(message_or_cb_message: Message, role: str, active_id: int | None) -> None:
    if role == "owner":
        await message_or_cb_message.answer(
            "Owner Panel" if not active_id else f"Owner Panel (Target: {await db.get_manager_title(active_id)})",
            reply_markup=owner_panel(active_id),
        )
    else:
        await message_or_cb_message.answer(
            "Admin Panel" if not active_id else f"Admin Panel (Target: {await db.get_manager_title(active_id)})",
            reply_markup=admin_panel(active_id),
        )


async def _edit_panel(cb: CallbackQuery, role: str, active_id: int | None) -> None:
    # همان ظاهر keyboards.py را حفظ می‌کنیم
    text = "Owner Panel" if role == "owner" else "Admin Panel"
    if active_id:
        title = await db.get_manager_title(active_id)
        text = f"{text} (Target: {title})"

    markup = owner_panel(active_id) if role == "owner" else admin_panel(active_id)

    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except Exception:
        # اگر edit نشد، fall back
        await cb.message.answer(text, reply_markup=markup)


# -----------------------------
# /panel entry
# -----------------------------
@router.message(Command("panel"))
async def open_panel(message: Message, state: FSMContext):
    if not message.from_user:
        return
    uid = int(message.from_user.id)

    # گروه: همان‌جا پنل همان مدیریت
    if _is_group(message.chat.type):
        effective = await _resolve_effective(message.chat.id)

        if not await _has_access(uid, effective):
            await message.answer("دسترسی ندارید.")
            return

        role = "owner" if is_owner(uid) else "admin"
        await state.clear()
        await state.update_data(active_chat_id=effective, panel_role=role, nav_stack=[])
        await _render_panel(message, role, effective)
        return

    # PV:
    # owner => باید انتخاب کند
    if is_owner(uid):
        await state.clear()
        await state.update_data(active_chat_id=None, panel_role="owner", nav_stack=[])
        await _render_panel(message, "owner", None)
        return

    # admin => اگر یک manager دارد مستقیم، اگر چندتا دارد لیست
    try:
        mids = await db.list_managers_for_admin(uid)
    except Exception:
        mids = []

    if not mids:
        # legacy global admin هم اگر باشد اجازه بدهیم target انتخاب کند (ولی باید از owner لیست نگیرد)
        try:
            if await db.is_admin(uid):
                await state.clear()
                await state.update_data(active_chat_id=None, panel_role="admin", nav_stack=[])
                await _render_panel(message, "admin", None)
                return
        except Exception:
            pass

        await message.answer("شما ادمین هیچ گروه مدیریتی نیستید. داخل گروه مدیریت /panel بزن.")
        return

    if len(mids) == 1:
        effective = int(mids[0])
        await state.clear()
        await state.update_data(active_chat_id=effective, panel_role="admin", nav_stack=[])
        await _render_panel(message, "admin", effective)
        return

    # چند مدیریت: لیست انتخاب
    await state.clear()
    await state.update_data(active_chat_id=None, panel_role="admin", nav_stack=[])
    await message.answer("برای شروع 🎯 Select Group/Channel رو بزن و مدیریت رو انتخاب کن.", reply_markup=admin_panel(None))


# -----------------------------
# ctx:select (target picker)
# -----------------------------
@router.callback_query(F.data == "ctx:select")
async def ctx_select(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)

    uid = int(cb.from_user.id)
    data = await state.get_data()
    role = data.get("panel_role") or ("owner" if is_owner(uid) else "admin")

    kb = InlineKeyboardBuilder()

    if role == "owner":
        managers = await db.list_manager_groups()  # [(mid,title,limit)]
        for mid, title, limit in managers[:50]:
            t = (title or str(mid)).strip() or str(mid)
            kb.button(text=f"{t} (limit={limit})", callback_data=f"ctx:set:{mid}")
    else:
        mids = await db.list_managers_for_admin(uid)
        for mid in mids[:50]:
            t = await db.get_manager_title(mid)
            kb.button(text=t, callback_data=f"ctx:set:{mid}")

    kb.button(text="❌ Cancel", callback_data="cancel")
    kb.adjust(1)

    # اینجا شلوغ‌کاری نکنیم: همان پیام را edit کنیم
    try:
        await cb.message.edit_text("مدیریت رو انتخاب کن:", reply_markup=kb.as_markup())
    except Exception:
        await cb.message.answer("مدیریت رو انتخاب کن:", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("ctx:set:"))
async def ctx_set(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)

    uid = int(cb.from_user.id)
    data = await state.get_data()
    role = data.get("panel_role") or ("owner" if is_owner(uid) else "admin")

    try:
        _, _, chat_id_str = cb.data.split(":")
        target = int(chat_id_str)
    except Exception:
        await cb.message.answer("Bad data.")
        return

    if not await _has_access(uid, target):
        await cb.message.answer("دسترسی ندارید.")
        return

    await state.update_data(active_chat_id=target, panel_role=role)
    await _edit_panel(cb, role, target)


# -----------------------------
# cancel / back
# -----------------------------
@router.callback_query(F.data == "cancel")
async def cancel_action(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)
    await state.clear()
    try:
        await cb.message.edit_text("Cancelled.")
    except Exception:
        await cb.message.answer("Cancelled.")


@router.callback_query(F.data == "nav:back")
async def nav_back(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)
    data = await state.get_data()
    data, last = _pop_nav(dict(data))
    await state.set_data(data)

    uid = int(cb.from_user.id)
    role = data.get("panel_role") or ("owner" if is_owner(uid) else "admin")
    active = data.get("active_chat_id")
    await _edit_panel(cb, role, active)

@router.callback_query(F.data == "panel:refresh")
async def panel_refresh(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)
    data = await state.get_data()
    uid = int(cb.from_user.id)
    role = data.get("panel_role") or ("owner" if is_owner(uid) else "admin")
    active = data.get("active_chat_id")
    await _edit_panel(cb, role, active)


@router.callback_query(F.data == "owner:home")
async def owner_home(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)
    uid = int(cb.from_user.id)
    if not is_owner(uid):
        await cb.message.answer("دسترسی ندارید.")
        return
    data = await state.get_data()
    role = data.get("panel_role") or "owner"
    await state.update_data(active_chat_id=None, panel_role=role)
    await _edit_panel(cb, role, None)


@router.callback_query(F.data == "owner:manage")
async def owner_manage(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)
    uid = int(cb.from_user.id)
    if not is_owner(uid):
        await cb.message.answer("دسترسی ندارید.")
        return

    data = await state.get_data()
    active = data.get("active_chat_id")
    if not active:
        await cb.message.answer("اول یک Management انتخاب کن (🎯 Select Management).")
        return

    try:
        await cb.message.edit_text("🧩 Owner Manage:", reply_markup=owner_manage_submenu())
    except Exception:
        await cb.message.answer("🧩 Owner Manage:", reply_markup=owner_manage_submenu())


@router.callback_query(F.data == "owner:manage_admins")
async def owner_manage_admins(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)
    uid = int(cb.from_user.id)
    if not is_owner(uid):
        await cb.message.answer("دسترسی ندارید.")
        return

    data = await state.get_data()
    active = data.get("active_chat_id")
    if not active:
        await cb.message.answer("اول یک Management انتخاب کن.")
        return

    title = await db.get_manager_title(int(active))
    text = f"👮 Admins for «{title}»\n\nبرای افزودن ادمین، دکمه Add Admin رو بزن."
    try:
        await cb.message.edit_text(text, reply_markup=owner_manage_admins_menu())
    except Exception:
        await cb.message.answer(text, reply_markup=owner_manage_admins_menu())


@router.callback_query(F.data == "owner:manage_mgmt")
async def owner_manage_mgmt(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)
    uid = int(cb.from_user.id)
    if not is_owner(uid):
        await cb.message.answer("دسترسی ندارید.")
        return

    data = await state.get_data()
    active = data.get("active_chat_id")
    if not active:
        await cb.message.answer("اول یک Management انتخاب کن.")
        return

    title = await db.get_manager_title(int(active))
    text = f"🏷 Management Settings for «{title}»"
    try:
        await cb.message.edit_text(text, reply_markup=owner_manage_mgmt_menu())
    except Exception:
        await cb.message.answer(text, reply_markup=owner_manage_mgmt_menu())

# -----------------------------
# OWNER: add global admin (legacy button in keyboards.py)
# -----------------------------
@router.callback_query(F.data == "owner:add_admin")

async def owner_add_admin(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)

    uid = int(cb.from_user.id)
    if not is_owner(uid):
        await cb.message.answer("دسترسی ندارید.")
        return

    data = await state.get_data()
    active = data.get("active_chat_id")

    op = "add_admin_manager" if active else "add_admin_global"

    prompt = "آیدی عددی / @username را بفرست یا روی پیام کاربر ریپلای کن تا ادمین شود."
    if active:
        title = await db.get_manager_title(int(active))
        prompt = f"{prompt}\n\nTarget: «{title}»"

    await _start_input_flow(
        cb,
        state,
        pending={
            "op": op,
            "scope_manager_id": int(active) if active else None,
            "target_chat_id": None,
            "extra": {},
        },
        prompt=prompt,
    )
@router.callback_query(F.data == "admin:remove_safe")
async def remove_safe_start(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)

    uid = int(cb.from_user.id)
    data = await state.get_data()
    active = data.get("active_chat_id")

    if not active:
        await cb.message.answer("اول Target (مدیریت) رو انتخاب کن. روی 🎯 Select Group/Channel بزن.")
        return

    if not await _has_access(uid, int(active)):
        await cb.message.answer("دسترسی ندارید.")
        return

    title = await db.get_manager_title(int(active))
    prompt = f"➖ Remove Safe\nTarget: «{title}»\n\nآیدی عددی / @username را بفرست یا ریپلای کن."

    await _start_input_flow(
        cb,
        state,
        pending={
            "op": "remove_safe",
            "scope_manager_id": int(active),
            "target_chat_id": None,
            "extra": {},
        },
        prompt=prompt,
    )


# -----------------------------
# SAFE buttons
# -----------------------------
@router.callback_query(F.data == "admin:add_safe")
async def add_safe_start(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)

    uid = int(cb.from_user.id)
    data = await state.get_data()
    active = data.get("active_chat_id")

    if not active:
        await cb.message.answer("اول Target (مدیریت) رو انتخاب کن. روی 🎯 Select Group/Channel بزن.")
        return

    if not await _has_access(uid, int(active)):
        await cb.message.answer("دسترسی ندارید.")
        return

    title = await db.get_manager_title(int(active))
    prompt = f"✅ Add Safe\nTarget: «{title}»\n\nآیدی عددی / @username را بفرست یا ریپلای کن."

    await _start_input_flow(
        cb,
        state,
        pending={
            "op": "add_safe",
            "scope_manager_id": int(active),
            "target_chat_id": None,
            "extra": {},
        },
        prompt=prompt,
    )

def _extract_first_int(text: str | None) -> int | None:
    m = re.search(r"-?\d{3,}", (text or "").strip())
    if not m:
        return None
    try:
        return int(m.group(0))
    except Exception:
        return None


@router.callback_query(F.data == "mgmt:create")
async def mgmt_create(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)
    uid = int(cb.from_user.id)
    if not is_owner(uid):
        await cb.message.answer("دسترسی ندارید.")
        return

    prompt = (
        "➕ Create Management\n"
        "آیدی عددی گروه/کانال را بفرست.\n"
        "مثال: -1001234567890"
    )
    await _start_input_flow(
        cb,
        state,
        pending={"op": "mgmt_create", "scope_manager_id": None, "target_chat_id": None, "extra": {}},
        prompt=prompt,
        back_cb="panel:refresh",
    )


@router.callback_query(F.data == "mgmt:set_limit")
async def mgmt_set_limit(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)
    uid = int(cb.from_user.id)
    if not is_owner(uid):
        await cb.message.answer("دسترسی ندارید.")
        return

    data = await state.get_data()
    active = data.get("active_chat_id")
    if not active:
        await cb.message.answer("اول یک Management انتخاب کن.")
        return

    title = await db.get_manager_title(int(active))
    prompt = (
        f"🔢 Set Child Limit\nTarget: «{title}»\n\n"
        "فقط عدد limit را بفرست (مثلاً 10)."
    )
    await _start_input_flow(
        cb,
        state,
        pending={"op": "mgmt_set_limit", "scope_manager_id": int(active), "target_chat_id": None, "extra": {}},
        prompt=prompt,
        back_cb="owner:manage_mgmt",
    )


@router.callback_query(F.data == "mgmt:link_child")
async def mgmt_link_child(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)
    uid = int(cb.from_user.id)
    if not is_owner(uid):
        await cb.message.answer("دسترسی ندارید.")
        return

    data = await state.get_data()
    active = data.get("active_chat_id")
    if not active:
        await cb.message.answer("اول یک Management انتخاب کن.")
        return

    title = await db.get_manager_title(int(active))
    prompt = (
        f"🔗 Link Child\nTarget: «{title}»\n\n"
        "آیدی عددی گروه Child را بفرست.\n"
        "مثال: -1001234567890"
    )
    await _start_input_flow(
        cb,
        state,
        pending={"op": "mgmt_link_child", "scope_manager_id": int(active), "target_chat_id": None, "extra": {}},
        prompt=prompt,
        back_cb="owner:manage_mgmt",
    )


@router.callback_query(F.data == "mgmt:unlink_child")
async def mgmt_unlink_child(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)
    uid = int(cb.from_user.id)
    if not is_owner(uid):
        await cb.message.answer("دسترسی ندارید.")
        return

    data = await state.get_data()
    active = data.get("active_chat_id")
    if not active:
        await cb.message.answer("اول یک Management انتخاب کن.")
        return

    title = await db.get_manager_title(int(active))
    prompt = (
        f"🔓 Unlink Child\nTarget: «{title}»\n\n"
        "آیدی عددی گروه Child را بفرست."
    )
    await _start_input_flow(
        cb,
        state,
        pending={"op": "mgmt_unlink_child", "scope_manager_id": int(active), "target_chat_id": None, "extra": {}},
        prompt=prompt,
        back_cb="owner:manage_mgmt",
    )


# -----------------------------
# BAN / UNBAN buttons
# behavior:
#   - Ban(Target) & Unban(Target): اول لیست childها + manager را می‌دهد، سپس user id می‌گیرد و فقط همان chat را ban/unban می‌کند
#   - Global Ban/Unban: مستقیم user id می‌گیرد و روی manager+children اعمال می‌کند
# -----------------------------
async def _scope_chats(manager_id: int) -> list[int]:
    mids = [int(manager_id)]
    try:
        children = await db.list_children(int(manager_id))
    except Exception:
        children = []
    for c in children:
        if int(c) not in mids:
            mids.append(int(c))
    return mids


async def _pick_chat_menu(cb: CallbackQuery, state: FSMContext, title: str, action_prefix: str):
    data = await state.get_data()
    manager_id = data.get("active_chat_id")
    if not manager_id:
        await cb.message.answer("اول Target (مدیریت) رو انتخاب کن. روی 🎯 Select Group/Channel بزن.")
        return

    uid = int(cb.from_user.id)
    if not await _has_access(uid, int(manager_id)):
        await cb.message.answer("دسترسی ندارید.")
        return

    chats = await _scope_chats(int(manager_id))

    kb = InlineKeyboardBuilder()
    for cid in chats[:60]:
        t = await db.get_group_title(int(cid))
        kb.button(text=t, callback_data=f"{action_prefix}:{cid}")
    kb.button(text="⬅️ Back", callback_data="nav:back")
    kb.button(text="❌ Cancel", callback_data="cancel")
    kb.adjust(1)

    try:
        await cb.message.edit_text(title, reply_markup=kb.as_markup())
    except Exception:
        await cb.message.answer(title, reply_markup=kb.as_markup())


@router.callback_query(F.data == "ban:target")
async def ban_target_menu(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)
    await _pick_chat_menu(cb, state, "⛔ Ban (Target)\nیک گروه را انتخاب کن:", "banpick")


@router.callback_query(F.data == "admin:unban")
async def unban_target_menu_admin(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)
    await _pick_chat_menu(cb, state, "🔓 Unban (Target)\nیک گروه را انتخاب کن:", "unbanpick")


@router.callback_query(F.data == "owner:unban")
async def unban_target_menu_owner(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)
    await _pick_chat_menu(cb, state, "🔓 Unban (Target)\nیک گروه را انتخاب کن:", "unbanpick")


@router.callback_query(F.data.startswith("banpick:"))
async def ban_pick_chat(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)
    data = await state.get_data()
    manager_id = int(data.get("active_chat_id") or 0)
    uid = int(cb.from_user.id)

    try:
        target_chat_id = int(cb.data.split(":")[1])
    except Exception:
        await cb.message.answer("Bad data.")
        return

    if not manager_id or not await _has_access(uid, manager_id):
        await cb.message.answer("دسترسی ندارید.")
        return

    gtitle = await db.get_group_title(int(target_chat_id))
    prompt = f"⛔ Ban (Target)\nGroup: «{gtitle}»\n\nآیدی عددی / @username را بفرست یا ریپلای کن."

    await _start_input_flow(
         cb,
         state,
          pending={
              "op": "ban_one",
              "scope_manager_id": manager_id,
              "target_chat_id": int(target_chat_id),
              "extra": {},
        },
         prompt=prompt,
    )


@router.callback_query(F.data.startswith("unbanpick:"))
async def unban_pick_chat(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)
    data = await state.get_data()
    manager_id = int(data.get("active_chat_id") or 0)
    uid = int(cb.from_user.id)

    try:
        target_chat_id = int(cb.data.split(":")[1])
    except Exception:
        await cb.message.answer("Bad data.")
        return

    if not manager_id or not await _has_access(uid, manager_id):
        await cb.message.answer("دسترسی ندارید.")
        return

    gtitle = await db.get_group_title(int(target_chat_id))
    prompt = f"🔓 Unban (Target)\nGroup: «{gtitle}»\n\nآیدی عددی / @username را بفرست یا ریپلای کن."

    await _start_input_flow(
    cb,
    state,
    pending={
        "op": "unban_one",
        "scope_manager_id": manager_id,
        "target_chat_id": int(target_chat_id),
        "extra": {},
    },
    prompt=prompt,
)


@router.callback_query(F.data == "ban:global")
async def gban_start(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)
    data = await state.get_data()
    manager_id = data.get("active_chat_id")

    if not manager_id:
        await cb.message.answer("اول Target (مدیریت) رو انتخاب کن. روی 🎯 Select Group/Channel بزن.")
        return

    uid = int(cb.from_user.id)
    if not await _has_access(uid, int(manager_id)):
        await cb.message.answer("دسترسی ندارید.")
        return

    title = await db.get_manager_title(int(manager_id))
    prompt = f"🌍 Global Ban\nScope: «{title}» + زیرمجموعه‌ها\n\nآیدی عددی / @username را بفرست یا ریپلای کن."

    await _start_input_flow(
             cb,
             state,
             pending={
                 "op": "gban",
                 "scope_manager_id": int(manager_id),
                 "target_chat_id": None,
                 "extra": {},
             },
             prompt=prompt,
         )


@router.callback_query(F.data.in_({"admin:unban_global", "owner:unban_global"}))
async def gunban_start(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)
    data = await state.get_data()
    manager_id = data.get("active_chat_id")

    if not manager_id:
        await cb.message.answer("اول Target (مدیریت) رو انتخاب کن. روی 🎯 Select Group/Channel بزن.")
        return

    uid = int(cb.from_user.id)
    if not await _has_access(uid, int(manager_id)):
        await cb.message.answer("دسترسی ندارید.")
        return

    title = await db.get_manager_title(int(manager_id))
    prompt = f"🔓 Global Unban\nScope: «{title}» + زیرمجموعه‌ها\n\nآیدی عددی / @username را بفرست یا ریپلای کن."

    await _start_input_flow(
         cb,
         state,
         pending={
             "op": "gunban",
             "scope_manager_id": int(manager_id),
             "target_chat_id": None,
             "extra": {},
         },
         prompt=prompt,
     )


# -----------------------------
# LINKS buttons (basic implementation)
# - manager link (one-time)
# - one child link (pick chat then one-time)
# - all children links (list)
# -----------------------------
@router.callback_query(F.data.in_({"owner:links", "admin:links"}))
async def links_menu(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)

    data = await state.get_data()
    manager_id = data.get("active_chat_id")
    if not manager_id:
        await cb.message.answer("اول Target (مدیریت) رو انتخاب کن. روی 🎯 Select Group/Channel بزن.")
        return

    uid = int(cb.from_user.id)
    if not await _has_access(uid, int(manager_id)):
        await cb.message.answer("دسترسی ندارید.")
        return

    kb = InlineKeyboardBuilder()
    kb.button(text="🔗 Link for Management", callback_data="link:manager")
    kb.button(text="🔗 Link for ONE child", callback_data="link:child_one")
    kb.button(text="🔗 Links for ALL children", callback_data="link:children_all")
    kb.button(text="⬅️ Back", callback_data="nav:back")
    kb.button(text="❌ Cancel", callback_data="cancel")
    kb.adjust(1)

    try:
        await cb.message.edit_text("🔗 Links menu:", reply_markup=kb.as_markup())
    except Exception:
        await cb.message.answer("🔗 Links menu:", reply_markup=kb.as_markup())


async def _make_one_time_invite(bot, chat_id: int) -> str | None:
    try:
        link = await bot.create_chat_invite_link(
            chat_id=int(chat_id),
            member_limit=1,
            creates_join_request=False,
        )
        return link.invite_link
    except Exception as e:
        log.warning("create_chat_invite_link failed chat=%s err=%s", chat_id, e)
        return None


@router.callback_query(F.data == "link:manager")
async def link_manager(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)
    data = await state.get_data()
    manager_id = int(data.get("active_chat_id") or 0)
    if not manager_id:
        await cb.message.answer("Target نداریم.")
        return

    uid = int(cb.from_user.id)
    if not await _has_access(uid, manager_id):
        await cb.message.answer("دسترسی ندارید.")
        return

    url = await _make_one_time_invite(cb.bot, manager_id)
    title = await db.get_manager_title(manager_id)

    kb = _kb_back_cancel("nav:back")
    if url:
        text = f"🔗 One-time link for Management «{title}»:\n{url}"
    else:
        text = f"❌ ساخت لینک برای «{title}» ناموفق بود (بات باید Admin با Invite permission باشد)."
    try:
        await cb.message.edit_text(text, reply_markup=kb.as_markup())
    except Exception:
        await cb.message.answer(text, reply_markup=kb.as_markup())


@router.callback_query(F.data == "link:child_one")
async def link_child_pick(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)
    await _pick_chat_menu(cb, state, "یک Child را انتخاب کن تا لینک یک‌بارمصرف بسازم:", "linkpick")


@router.callback_query(F.data.startswith("linkpick:"))
async def link_child_make(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)

    uid = int(cb.from_user.id)
    data = await state.get_data()
    manager_id = int(data.get("active_chat_id") or 0)

    try:
        child_id = int(cb.data.split(":")[1])
    except Exception:
        await cb.message.answer("Bad data.")
        return

    if not manager_id or not await _has_access(uid, manager_id):
        await cb.message.answer("دسترسی ندارید.")
        return

    url = await _make_one_time_invite(cb.bot, child_id)
    title = await db.get_group_title(child_id)

    kb = _kb_back_cancel("nav:back")
    if url:
        text = f"🔗 One-time link for «{title}»:\n{url}"
    else:
        text = f"❌ ساخت لینک برای «{title}» ناموفق بود (بات باید Admin با Invite permission باشد)."
    try:
        await cb.message.edit_text(text, reply_markup=kb.as_markup())
    except Exception:
        await cb.message.answer(text, reply_markup=kb.as_markup())


@router.callback_query(F.data == "link:children_all")
async def link_children_all(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)
    data = await state.get_data()
    manager_id = int(data.get("active_chat_id") or 0)
    if not manager_id:
        await cb.message.answer("Target نداریم.")
        return

    uid = int(cb.from_user.id)
    if not await _has_access(uid, manager_id):
        await cb.message.answer("دسترسی ندارید.")
        return

    children = await db.list_children(manager_id)
    kb = _kb_back_cancel("nav:back")

    if not children:
        text = "این مدیریت child ندارد."
        try:
            await cb.message.edit_text(text, reply_markup=kb.as_markup())
        except Exception:
            await cb.message.answer(text, reply_markup=kb.as_markup())
        return

    lines = ["🔗 One-time links for ALL children:\n"]
    ok = 0
    for cid in children[:30]:
        t = await db.get_group_title(int(cid))
        url = await _make_one_time_invite(cb.bot, int(cid))
        if url:
            ok += 1
            lines.append(f"- {t}: {url}")
        else:
            lines.append(f"- {t}: ❌ failed")

    lines.append(f"\nResult: {ok}/{min(len(children),30)}")
    text = "\n".join(lines)

    try:
        await cb.message.edit_text(text, reply_markup=kb.as_markup())
    except Exception:
        await cb.message.answer(text, reply_markup=kb.as_markup())


# -----------------------------
# LISTS buttons (keep working)
# -----------------------------
@router.callback_query(F.data.in_({"owner:lists", "admin:lists"}))
async def show_lists_target(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)

    uid = int(cb.from_user.id)
    data = await state.get_data()
    target_id = data.get("active_chat_id")
    if not target_id:
        await cb.message.answer("اول Target (مدیریت) رو انتخاب کن. روی 🎯 Select Group/Channel بزن.")
        return

    if not await _has_access(uid, int(target_id)):
        await cb.message.answer("دسترسی ندارید.")
        return

    safe_ids = await db.list_safe(int(target_id))
    admin_ids = await db.list_admins()
    bans = await db.list_bans(int(target_id))
    groups = await db.list_groups()

    lines = [f"📋 Lists (Target={target_id})\n"]
    lines.append(f"✅ SAFE users: {len(safe_ids)}")
    for x in safe_ids[:30]:
        lines.append(await _format_user(cb.bot, x))
    if len(safe_ids) > 30:
        lines.append("...")

    lines.append("")
    lines.append(f"🛡️ Admins (legacy/global): {len(admin_ids)}")
    for x in admin_ids[:30]:
        lines.append(await _format_user(cb.bot, x))
    if len(admin_ids) > 30:
        lines.append("...")

    lines.append("")
    lines.append(f"⛔ Bans (Target): {len(bans)}")
    for (u, _g) in bans[:30]:
        lines.append(f"{u} @ {target_id}")
    if len(bans) > 30:
        lines.append("...")

    lines.append("")
    lines.append(f"👥 Groups: {len(groups)}")
    for (gid, title, tp) in groups[:30]:
        lines.append(f"{gid} | {title or '-'} | {tp}")

    kb = _kb_back_cancel("nav:back")
    text = "\n".join(lines)
    try:
        await cb.message.edit_text(text, reply_markup=kb.as_markup())
    except Exception:
        await cb.message.answer(text, reply_markup=kb.as_markup())


@router.callback_query(F.data.in_({"owner:lists_global", "admin:lists_global"}))
async def show_lists_global(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)

    uid = int(cb.from_user.id)
    # global list فقط owner یا global admin
    if not (is_owner(uid) or await db.is_admin(uid)):
        await cb.message.answer("دسترسی ندارید.")
        return

    safe_ids = await db.list_safe(None)
    bans = await db.list_bans(None)

    lines = ["📋 Lists (GLOBAL)\n"]
    lines.append(f"✅ GLOBAL SAFE: {len(safe_ids)}")
    for x in safe_ids[:30]:
        lines.append(await _format_user(cb.bot, x))
    if len(safe_ids) > 30:
        lines.append("...")

    lines.append("")
    lines.append(f"⛔ GLOBAL BANS: {len(bans)}")
    for (u, _g) in bans[:30]:
        lines.append(str(u))
    if len(bans) > 30:
        lines.append("...")

    kb = _kb_back_cancel("nav:back")
    text = "\n".join(lines)
    try:
        await cb.message.edit_text(text, reply_markup=kb.as_markup())
    except Exception:
        await cb.message.answer(text, reply_markup=kb.as_markup())


# -----------------------------
# placeholders (folders/clone)
# -----------------------------
@router.callback_query(F.data.in_({"owner:folders", "admin:folders"}))
async def folders_placeholder(cb: CallbackQuery):
    await _safe_answer(cb)
    kb = _kb_back_cancel("nav:back")
    text = "📂 Folders: فعلاً در این نسخه UI کامل نشده."
    try:
        await cb.message.edit_text(text, reply_markup=kb.as_markup())
    except Exception:
        await cb.message.answer(text, reply_markup=kb.as_markup())


@router.callback_query(F.data == "clone:menu")
async def clone_placeholder(cb: CallbackQuery):
    await _safe_answer(cb)
    kb = _kb_back_cancel("nav:back")
    text = "🧬 Clone: فعلاً در این نسخه UI کامل نشده."
    try:
        await cb.message.edit_text(text, reply_markup=kb.as_markup())
    except Exception:
        await cb.message.answer(text, reply_markup=kb.as_markup())


# -----------------------------
# INPUT handler for all pending ops
# -----------------------------
@router.message()
async def panel_input_router(message: Message, state: FSMContext):
    st = await state.get_state()
    if st != ST_WAIT_INPUT:
        return

    if not message.from_user:
        return

    data = await state.get_data()
    
    pending = data.get("pending") or {}

    origin_chat_id = int(pending.get("origin_chat_id") or 0)
    origin_user_id = int(pending.get("origin_user_id") or 0)

# فقط همان کسی که عملیات را شروع کرده
    if origin_user_id and int(message.from_user.id) != origin_user_id:
         return

# ورودی معتبر: یا همان چت شروع‌کننده، یا PV همان کاربر
    same_chat = origin_chat_id and int(message.chat.id) == origin_chat_id
    private_ok = (message.chat.type == "private") and (int(message.chat.id) == int(message.from_user.id))

    if not (same_chat or private_ok):
         return




    uid = int(message.from_user.id)

    op = pending.get("op")
    manager_id = pending.get("scope_manager_id")
    target_chat_id = pending.get("target_chat_id")

        # --------- Management ops (owner only) ---------
    if op in {"mgmt_create", "mgmt_set_limit", "mgmt_link_child", "mgmt_unlink_child"}:
        if not is_owner(uid):
            await message.reply("دسترسی ندارید.")
            await state.clear()
            return

        val = _extract_first_int(message.text)
        if val is None:
            await message.reply("عدد معتبر پیدا نشد. فقط عدد بفرست.")
            return

        if op == "mgmt_create":
            chat_id = int(val)
            try:
                ch = await message.bot.get_chat(chat_id)
                title = getattr(ch, "title", None) or getattr(ch, "full_name", None) or str(chat_id)
            except Exception:
                title = str(chat_id)

            await db.upsert_group(chat_id=chat_id, title=title, chat_type="group")
            await db.upsert_manager_group(chat_id, title=title)

            await state.update_data(active_chat_id=chat_id, panel_role="owner")
            await state.clear()
            await message.reply(f"✅ Management ساخته شد: {title} ({chat_id})")
            return

        if not manager_id:
            await message.reply("Target management نداریم. اول انتخاب کن.")
            return

        mid = int(manager_id)

        if op == "mgmt_set_limit":
            limit = int(val)
            if limit < 0:
                await message.reply("limit باید صفر یا مثبت باشد.")
                return
            await db.set_manager_limit(mid, limit)
            await state.clear()
            title = await db.get_manager_title(mid)
            await message.reply(f"✅ limit برای «{title}» شد: {limit}")
            return

        if op == "mgmt_link_child":
            child_id = int(val)
            ok, msg = await db.link_child(mid, child_id)
            await state.clear()
            title = await db.get_manager_title(mid)
            await message.reply(f"{'✅' if ok else '❌'} {msg}\nTarget: «{title}»\nchild={child_id}")
            return

        if op == "mgmt_unlink_child":
            child_id = int(val)
            ok, msg = await db.unlink_child(child_id)
            await state.clear()
            await message.reply(f"{'✅' if ok else '❌'} {msg}\nchild={child_id}")
            return


    if manager_id:
        if not await _has_access(uid, int(manager_id)):
            await message.reply("دسترسی ندارید.")
            return

    # resolve user id
    target_user_id = await resolve_target_user_id(message)
    if not target_user_id:
        await message.reply(
            "کاربر پیدا نشد.\n"
            "- بهترین راه: ریپلای روی پیام کاربر\n"
            "- یا آیدی عددی\n"
            "- یا mention واقعی (نه متن ساده)\n"
            "اگر @username را تلگرام برای بات قابل resolve نکند، مجبوریم ریپلای/ID بدهی."
        )
        return

    # prevent banning bot/self
    me_id = await _get_me_id(message.bot)
    if int(target_user_id) == int(me_id):
        await message.reply("❌ نمی‌توانم خودِ بات را ban/unban کنم.")
        return

    # ------------------ actions ------------------
    try:
        if op == "add_admin_global":
            if not is_owner(uid):
                await message.reply("دسترسی ندارید.")
                return
            await db.add_admin(int(target_user_id))
            await state.clear()
            await message.reply(f"✅ Added GLOBAL admin: {await _format_user(message.bot, int(target_user_id))}")
            return

        if op == "add_admin_manager":
            if not is_owner(uid):
                await message.reply("دسترسی ندارید.")
                return
            mid = int(manager_id)
            await db.add_manager_admin(mid, int(target_user_id))
            await state.clear()
            title = await db.get_manager_title(mid)
            await message.reply(f"✅ Added admin for «{title}»: {await _format_user(message.bot, int(target_user_id))}")
            return

        if op == "add_safe":
            mid = int(manager_id)
            await db.add_safe(int(target_user_id), chat_id=mid)
            await state.clear()
            title = await db.get_manager_title(mid)
            await message.reply(f"✅ SAFE added for «{title}»: {await _format_user(message.bot, int(target_user_id))}")
            return

        if op == "remove_safe":
            mid = int(manager_id)
            await db.remove_safe(int(target_user_id), chat_id=mid)
            await state.clear()
            title = await db.get_manager_title(mid)
            await message.reply(f"➖ SAFE removed for «{title}»: {await _format_user(message.bot, int(target_user_id))}")
            return

        if op == "ban_one":
            cid = int(target_chat_id)
            try:
                await message.bot.ban_chat_member(chat_id=cid, user_id=int(target_user_id))
                await db.add_ban(int(target_user_id), cid)
                await state.clear()
                t = await db.get_group_title(cid)
                await message.reply(f"⛔ Banned in «{t}»: {await _format_user(message.bot, int(target_user_id))}")
            except Exception as e:
                await message.reply(f"❌ Ban ناموفق.\nuser={target_user_id}\nTarget={cid}\nError:\n{e}")
            return

        if op == "unban_one":
            cid = int(target_chat_id)
            try:
                await message.bot.unban_chat_member(chat_id=cid, user_id=int(target_user_id), only_if_banned=True)
                await db.remove_ban(int(target_user_id), cid)
                await state.clear()
                t = await db.get_group_title(cid)
                await message.reply(f"🔓 Unbanned in «{t}»: {await _format_user(message.bot, int(target_user_id))}")
            except Exception as e:
                await message.reply(f"❌ Unban ناموفق.\nuser={target_user_id}\nTarget={cid}\nError:\n{e}")
            return

        if op == "gban":
            mid = int(manager_id)
            chats = await _scope_chats(mid)
            ok = 0
            fail = 0
            last_err = None
            for cid in chats:
                try:
                    await message.bot.ban_chat_member(chat_id=int(cid), user_id=int(target_user_id))
                    await db.add_ban(int(target_user_id), int(cid))
                    ok += 1
                except Exception as e:
                    fail += 1
                    last_err = str(e)
            await state.clear()
            title = await db.get_manager_title(mid)
            txt = f"🌍 GBAN «{title}»\nuser={await _format_user(message.bot, int(target_user_id))}\nok={ok} fail={fail}"
            if last_err:
                txt += f"\nlast_error={last_err}"
            await message.reply(txt)
            return

        if op == "gunban":
            mid = int(manager_id)
            chats = await _scope_chats(mid)
            ok = 0
            fail = 0
            last_err = None
            for cid in chats:
                try:
                    await message.bot.unban_chat_member(chat_id=int(cid), user_id=int(target_user_id), only_if_banned=True)
                    await db.remove_ban(int(target_user_id), int(cid))
                    ok += 1
                except Exception as e:
                    fail += 1
                    last_err = str(e)
            await state.clear()
            title = await db.get_manager_title(mid)
            txt = f"🔓 GUNBAN «{title}»\nuser={await _format_user(message.bot, int(target_user_id))}\nok={ok} fail={fail}"
            if last_err:
                txt += f"\nlast_error={last_err}"
            await message.reply(txt)
            return

        # unknown op
        await message.reply("❌ عملیات نامعتبر.")
        await state.clear()
        return

    except Exception as e:
        log.exception("panel_input op failed op=%s err=%s", op, e)
        await message.reply(f"❌ خطای داخلی: {e}")
        await state.clear()
        return
