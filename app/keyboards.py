from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def owner_panel(active_chat_id: int | None = None) -> InlineKeyboardMarkup:
    label = "🎯 Select Group/Channel" if not active_chat_id else f"🎯 Target: {active_chat_id}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data="ctx:select")],

            [InlineKeyboardButton(text="➕ Add Admin", callback_data="owner:add_admin")],

            [InlineKeyboardButton(text="✅ Add Safe User", callback_data="admin:add_safe")],
            [InlineKeyboardButton(text="➖ Remove Safe User", callback_data="admin:remove_safe")],

            [InlineKeyboardButton(text="⛔ Ban (Target)", callback_data="ban:target")],
            [InlineKeyboardButton(text="🌍 Global Ban", callback_data="ban:global")],
            [InlineKeyboardButton(text="🔓 Unban (Target)", callback_data="owner:unban")],
            [InlineKeyboardButton(text="🔓 Unban (Global)", callback_data="owner:unban_global")],

            [InlineKeyboardButton(text="📂 Manage Folders", callback_data="owner:folders")],
            [InlineKeyboardButton(text="🔗 Links", callback_data="owner:links")],

            [InlineKeyboardButton(text="📋 Lists (Target)", callback_data="owner:lists")],
            [InlineKeyboardButton(text="📋 Lists (Global)", callback_data="owner:lists_global")],

            [InlineKeyboardButton(text="🧬 Clone from Target…", callback_data="clone:menu")],
        ]
    )


def admin_panel(active_chat_id: int | None = None) -> InlineKeyboardMarkup:
    label = "🎯 Select Group/Channel" if not active_chat_id else f"🎯 Target: {active_chat_id}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data="ctx:select")],

            [InlineKeyboardButton(text="✅ Add Safe User", callback_data="admin:add_safe")],
            [InlineKeyboardButton(text="➖ Remove Safe User", callback_data="admin:remove_safe")],

            [InlineKeyboardButton(text="⛔ Ban (Target)", callback_data="ban:target")],
            [InlineKeyboardButton(text="🌍 Global Ban", callback_data="ban:global")],
            [InlineKeyboardButton(text="🔓 Unban (Target)", callback_data="admin:unban")],
            [InlineKeyboardButton(text="🔓 Unban (Global)", callback_data="admin:unban_global")],

            [InlineKeyboardButton(text="📂 Folders", callback_data="admin:folders")],
            [InlineKeyboardButton(text="🔗 Links", callback_data="admin:links")],

            [InlineKeyboardButton(text="📋 Lists (Target)", callback_data="admin:lists")],
            [InlineKeyboardButton(text="📋 Lists (Global)", callback_data="admin:lists_global")],

            [InlineKeyboardButton(text="🧬 Clone from Target…", callback_data="clone:menu")],
        ]
    )


def confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Confirm", callback_data=f"confirm:{action}"),
                InlineKeyboardButton(text="❌ Cancel", callback_data="cancel"),
            ]
        ]
    )
