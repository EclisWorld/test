# app/keyboards.py
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def back_cancel_kb(back_cb: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Back", callback_data=back_cb)
    kb.button(text="✖️ Cancel", callback_data="cancel")
    kb.adjust(2)
    return kb.as_markup()


def owner_root_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    # مهم: باید با private_panel.py یکی باشد
    kb.button(text="🎯 Select Management", callback_data="ctx:select")
    kb.button(text="➕ Create Management", callback_data="mgmt:create")
    kb.button(text="✖️ Cancel", callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()


def owner_manager_menu(_mid: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    # Owner-only Manage entry
    kb.button(text="🧩 Manage", callback_data="owner:manage")

    kb.button(text="📋 Lists (Target)", callback_data="admin:lists")
    kb.button(text="📋 Lists (Global)", callback_data="admin:lists_global")

    kb.button(text="➕ Add SAFE", callback_data="admin:add_safe")
    kb.button(text="➖ Remove SAFE", callback_data="admin:remove_safe")

    kb.button(text="⛔ Ban (Target)", callback_data="ban:target")
    kb.button(text="🌍 Global Ban", callback_data="ban:global")
    kb.button(text="✅ Unban (Target)", callback_data="owner:unban")
    kb.button(text="🌍 Global Unban", callback_data="owner:unban_global")

    kb.button(text="🔗 Links", callback_data="owner:links")

    kb.button(text="🔄 Refresh", callback_data="panel:refresh")
    kb.button(text="⬅️ Back", callback_data="owner:home")
    kb.button(text="✖️ Cancel", callback_data="cancel")
    kb.adjust(2)
    return kb.as_markup()


def admin_manager_menu(_mid: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    kb.button(text="📋 Lists (Target)", callback_data="admin:lists")
    kb.button(text="📋 Lists (Global)", callback_data="admin:lists_global")

    kb.button(text="➕ Add SAFE", callback_data="admin:add_safe")
    kb.button(text="➖ Remove SAFE", callback_data="admin:remove_safe")

    kb.button(text="⛔ Ban (Target)", callback_data="ban:target")
    kb.button(text="✅ Unban (Target)", callback_data="admin:unban")

    kb.button(text="🔗 Links", callback_data="admin:links")

    kb.button(text="🔄 Refresh", callback_data="panel:refresh")
    kb.button(text="✖️ Cancel", callback_data="cancel")
    kb.adjust(2)
    return kb.as_markup()


def owner_manage_submenu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="👮 Admins", callback_data="owner:manage_admins")
    kb.button(text="🏷 Management", callback_data="owner:manage_mgmt")
    kb.button(text="⬅️ Back", callback_data="panel:refresh")
    kb.button(text="✖️ Cancel", callback_data="cancel")
    kb.adjust(2)
    return kb.as_markup()


def owner_manage_admins_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Add Admin (this management)", callback_data="owner:add_admin")
    kb.button(text="⬅️ Back", callback_data="owner:manage")
    kb.button(text="✖️ Cancel", callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()


def owner_manage_mgmt_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔢 Set Child Limit", callback_data="mgmt:set_limit")
    kb.button(text="🔗 Link Child", callback_data="mgmt:link_child")
    kb.button(text="🔓 Unlink Child", callback_data="mgmt:unlink_child")
    kb.button(text="⬅️ Back", callback_data="owner:manage")
    kb.button(text="✖️ Cancel", callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()


# ------------------------------------------------------------
# Compatibility layer
# ------------------------------------------------------------

def owner_panel(active_chat_id: int | None = None) -> InlineKeyboardMarkup:
    if active_chat_id:
        return owner_manager_menu(int(active_chat_id))
    return owner_root_menu()


def admin_panel(active_chat_id: int | None = None) -> InlineKeyboardMarkup:
    if active_chat_id:
        return admin_manager_menu(int(active_chat_id))

    # مهم: ادمین وقتی چند management دارد باید بتواند انتخاب کند
    kb = InlineKeyboardBuilder()
    kb.button(text="🎯 Select Group/Channel", callback_data="ctx:select")
    kb.button(text="✖️ Cancel", callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()


def confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Confirm", callback_data=f"confirm:{action}")
    kb.button(text="✖️ Cancel", callback_data="cancel")
    kb.adjust(2)
    return kb.as_markup()
