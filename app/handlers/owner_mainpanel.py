from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import is_owner
from app.db import db

router = Router()

# callback prefixes
P = "own:"  # owner


@router.message(Command("myid"))
async def myid(message: Message):
    uid = message.from_user.id if message.from_user else None
    await message.answer(f"user_id={uid}")


def kb_owner_home():
    kb = InlineKeyboardBuilder()
    kb.button(text="📁 گروه‌های مدیریتی", callback_data=P + "mgr:list")
    kb.button(text="🧩 درخواست‌های حذف", callback_data=P + "unlink:pending")
    kb.adjust(1)
    return kb.as_markup()


@router.message(Command("mainpanel"))
async def owner_mainpanel(message: Message):
    if not message.from_user or not is_owner(message.from_user.id):
        return
    await message.answer("پنل اصلی اونر", reply_markup=kb_owner_home())


@router.callback_query(F.data == P + "home")
async def owner_home(cb: CallbackQuery):
    if not cb.from_user or not is_owner(cb.from_user.id):
        await cb.answer("دسترسی ندارید", show_alert=True)
        return
    await cb.message.edit_text("پنل اصلی اونر", reply_markup=kb_owner_home())
    await cb.answer()


@router.callback_query(F.data == P + "mgr:list")
async def owner_list_managers(cb: CallbackQuery):
    if not cb.from_user or not is_owner(cb.from_user.id):
        await cb.answer("دسترسی ندارید", show_alert=True)
        return

    managers = await db.list_manager_groups()

    kb = InlineKeyboardBuilder()
    for mid, title, limit in managers:
        label = (title or "").strip() or str(mid)
        kb.button(text=f"⚙️ {label} (limit={limit})", callback_data=f"{P}mgr:open:{mid}")
    kb.button(text="➕ افزودن/ثبت گروه مدیریتی (از لیست گروه‌ها)", callback_data=P + "mgr:addpick")
    kb.button(text="⬅️ بازگشت", callback_data=P + "home")
    kb.adjust(1)

    await cb.message.edit_text("گروه‌های مدیریتی:", reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data == P + "mgr:addpick")
async def owner_pick_manager_from_groups(cb: CallbackQuery):
    if not cb.from_user or not is_owner(cb.from_user.id):
        await cb.answer("دسترسی ندارید", show_alert=True)
        return

    # این متد باید گروه‌هایی را بدهد که:
    # - گروه/سوپرگروه باشند
    # - manager نشده باشند
    # - childِ مدیریتی دیگری نشده باشند
    # اگر هنوز این متد را در db نداری، پایین‌تر توضیح داده‌ام.
    try:
        candidates = await db.list_manager_candidates()
        candidate_ids = set(candidates)
    except Exception:
        # fallback: اگر متد وجود ندارد، حداقل از list_groups می‌آوریم
        # (ولی بهتر است DB را درست کنی تا childها هم حذف شوند)
        groups = await db.list_groups()
        candidate_ids = {int(chat_id) for chat_id, title, chat_type in groups if chat_type in ("group", "supergroup")}

    kb = InlineKeyboardBuilder()
    for chat_id in sorted(candidate_ids):
        title = await db.get_group_title(chat_id)
        label = (title or "").strip() or str(chat_id)
        kb.button(text=f"➕ {label}", callback_data=f"{P}mgr:create:{chat_id}")

    kb.button(text="⬅️ بازگشت", callback_data=P + "mgr:list")
    kb.adjust(1)

    await cb.message.edit_text("کدام گروه را به‌عنوان «گروه مدیریتی» ثبت کنیم؟", reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith(P + "mgr:create:"))
async def owner_create_manager(cb: CallbackQuery):
    if not cb.from_user or not is_owner(cb.from_user.id):
        await cb.answer("دسترسی ندارید", show_alert=True)
        return

    manager_chat_id = int(cb.data.split(":")[-1])
    title = await db.get_group_title(manager_chat_id)
    await db.upsert_manager_group(manager_chat_id, title=title)

    await cb.answer("ثبت شد")
    await owner_list_managers(cb)


@router.callback_query(F.data.startswith(P + "mgr:open:"))
async def owner_open_manager(cb: CallbackQuery):
    if not cb.from_user or not is_owner(cb.from_user.id):
        await cb.answer("دسترسی ندارید", show_alert=True)
        return

    mid = int(cb.data.split(":")[-1])
    title = await db.get_manager_title(mid)
    limit = await db.get_manager_limit(mid)
    children = await db.list_children(mid)

    kb = InlineKeyboardBuilder()
    kb.button(text="🧷 افزودن چایلد", callback_data=f"{P}child:addpick:{mid}")
    kb.button(text="📏 تنظیم limit", callback_data=f"{P}mgr:setlimit:{mid}")
    kb.button(text="👤 مدیریت ادمین‌ها", callback_data=f"{P}mgr:admins:{mid}")
    kb.button(text="🧾 زیرمجموعه‌ها", callback_data=f"{P}child:list:{mid}")
    kb.button(text="⬅️ بازگشت", callback_data=P + "mgr:list")
    kb.adjust(1)

    text = f"مدیریت: {title}\nlimit: {limit}\nتعداد زیرمجموعه: {len(children)}"
    await cb.message.edit_text(text, reply_markup=kb.as_markup())
    await cb.answer()

    @router.callback_query(F.data.startswith(P + "child:rm:"))
    async def owner_remove_child(cb: CallbackQuery):
     if not cb.from_user or not is_owner(cb.from_user.id):
        await cb.answer("دسترسی ندارید", show_alert=True)
        return

    # own:child:rm:<mid>:<child_id>
    parts = cb.data.split(":")
    mid = int(parts[-2])
    child_id = int(parts[-1])

    await db.unlink_child(child_id)
    await cb.answer("حذف شد")
    await owner_open_manager(cb)



@router.callback_query(F.data.startswith(P + "mgr:setlimit:"))
async def owner_setlimit_hint(cb: CallbackQuery):
    if not cb.from_user or not is_owner(cb.from_user.id):
        await cb.answer("دسترسی ندارید", show_alert=True)
        return

    mid = int(cb.data.split(":")[-1])
    title = await db.get_manager_title(mid)
    await cb.message.edit_text(
        f"برای تنظیم limit این مدیریت ({title}) عدد را به شکل زیر در PV بفرست:\n\n/limitset {mid} 10",
        reply_markup=None
    )
    await cb.answer()


@router.message(Command("limitset"))
async def owner_limitset_command(message: Message):
    if not message.from_user or not is_owner(message.from_user.id):
        return

    parts = (message.text or "").strip().split()
    if len(parts) < 3:
        await message.answer("فرمت: /limitset <manager_chat_id> <limit>")
        return
    try:
        mid = int(parts[1])
        limit = int(parts[2])
    except Exception:
        await message.answer("فرمت: /limitset <manager_chat_id> <limit>")
        return

    title = await db.get_manager_title(mid)
    await db.upsert_manager_group(mid, title=title)
    await db.set_manager_limit(mid, limit)
    await message.answer(f"limit برای «{title}» تنظیم شد: {limit}")



@router.callback_query(F.data.startswith(P + "child:addpick:"))
async def owner_pick_child(cb: CallbackQuery):
    if not cb.from_user or not is_owner(cb.from_user.id):
        await cb.answer("دسترسی ندارید", show_alert=True)
        return

    mid = int(cb.data.split(":")[-1])
    manager_title = await db.get_manager_title(mid)

    # این متد باید فقط گروه‌های غیر-manager و غیر-child را بدهد
    candidates = await db.list_unlinked_groups()

    kb = InlineKeyboardBuilder()
    for child_id in candidates:
        child_title = await db.get_group_title(child_id)
        label = (child_title or "").strip() or str(child_id)
        kb.button(text=f"➕ {label}", callback_data=f"{P}child:confirm:{mid}:{child_id}")
    kb.button(text="⬅️ بازگشت", callback_data=f"{P}mgr:open:{mid}")
    kb.adjust(1)

    await cb.message.edit_text(f"انتخاب چایلد برای «{manager_title}»:", reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith(P + "child:confirm:"))
async def owner_confirm_link(cb: CallbackQuery):
    if not cb.from_user or not is_owner(cb.from_user.id):
        await cb.answer("دسترسی ندارید", show_alert=True)
        return

    # امن: هرچقدر prefix داشته باشد، دو تای آخر mid و child_id هستند
    *_, mid_s, child_s = cb.data.split(":")
    mid = int(mid_s)
    child_id = int(child_s)

    manager_title = await db.get_manager_title(mid)
    child_title = await db.get_group_title(child_id)

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ تایید", callback_data=f"{P}child:do:{mid}:{child_id}")
    kb.button(text="❌ لغو", callback_data=f"{P}mgr:open:{mid}")
    kb.adjust(2)

    await cb.message.edit_text(
        f"برای مدیریت «{manager_title}»، این زیرمجموعه اضافه شود؟\n\n• {child_title}",
        reply_markup=kb.as_markup()
    )
    await cb.answer()


@router.callback_query(F.data.startswith(P + "child:do:"))
async def owner_do_link(cb: CallbackQuery):
    if not cb.from_user or not is_owner(cb.from_user.id):
        await cb.answer("دسترسی ندارید", show_alert=True)
        return

    *_, mid_s, child_s = cb.data.split(":")
    mid = int(mid_s)
    child_id = int(child_s)

    ok, msg = await db.link_child(mid, child_id)
    manager_title = await db.get_manager_title(mid)
    child_title = await db.get_group_title(child_id)

    if ok:
        await cb.message.edit_text(f"✅ «{child_title}» زیرمجموعه «{manager_title}» شد.")
    else:
        await cb.message.edit_text(f"❌ انجام نشد: {msg}")

    await cb.answer()


@router.callback_query(F.data == P + "unlink:pending")
async def owner_pending_unlinks(cb: CallbackQuery):
    if not cb.from_user or not is_owner(cb.from_user.id):
        await cb.answer("دسترسی ندارید", show_alert=True)
        return

    reqs = await db.list_pending_unlink_requests()
    kb = InlineKeyboardBuilder()

    if not reqs:
        kb.button(text="⬅️ بازگشت", callback_data=P + "home")
        kb.adjust(1)
        await cb.message.edit_text("درخواست حذفِ در انتظار نداریم.", reply_markup=kb.as_markup())
        await cb.answer()
        return

    for req_id, mid, child_id, requested_by, created_at in reqs:
        mt = await db.get_manager_title(mid)
        ct = await db.get_group_title(child_id)
        kb.button(text=f"🧾 {mt} ← {ct}", callback_data=f"{P}unlink:open:{req_id}")

    kb.button(text="⬅️ بازگشت", callback_data=P + "home")
    kb.adjust(1)

    await cb.message.edit_text("درخواست‌های حذف:", reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith(P + "unlink:open:"))
async def owner_open_unlink(cb: CallbackQuery):
    if not cb.from_user or not is_owner(cb.from_user.id):
        await cb.answer("دسترسی ندارید", show_alert=True)
        return

    req_id = int(cb.data.split(":")[-1])
    row = await db.get_unlink_request(req_id)
    if not row:
        await cb.answer("یافت نشد", show_alert=True)
        return

    _, mid, child_id, requested_by, created_at = row
    mt = await db.get_manager_title(mid)
    ct = await db.get_group_title(child_id)

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ تایید حذف", callback_data=f"{P}unlink:approve:{req_id}")
    kb.button(text="❌ رد", callback_data=f"{P}unlink:deny:{req_id}")
    kb.button(text="⬅️ بازگشت", callback_data=P + "unlink:pending")
    kb.adjust(1)

    await cb.message.edit_text(
        f"درخواست حذف زیرمجموعه:\n\n"
        f"مدیریت: {mt}\n"
        f"زیرمجموعه: {ct}\n"
        f"درخواست‌دهنده: {requested_by}\n"
        f"زمان: {created_at}",
        reply_markup=kb.as_markup()
    )
    await cb.answer()

    @router.callback_query(F.data.startswith(P + "child:list:"))
    async def owner_list_children(cb: CallbackQuery):
     if not cb.from_user or not is_owner(cb.from_user.id):
        await cb.answer("دسترسی ندارید", show_alert=True)
        return

    mid = int(cb.data.split(":")[-1])
    mt = await db.get_manager_title(mid)
    children = await db.list_children(mid)

    kb = InlineKeyboardBuilder()
    for cid in children[:50]:
        ct = await db.get_group_title(cid)
        kb.button(text=f"🗑 {ct}", callback_data=f"{P}child:rm:{mid}:{cid}")
    kb.button(text="⬅️ بازگشت", callback_data=f"{P}mgr:open:{mid}")
    kb.adjust(1)

    await cb.message.edit_text(f"زیرمجموعه‌های «{mt}»:", reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith(P + "mgr:admins:"))
async def owner_mgr_admins(cb: CallbackQuery):
    if not cb.from_user or not is_owner(cb.from_user.id):
        await cb.answer("دسترسی ندارید", show_alert=True)
        return

    mid = int(cb.data.split(":")[-1])
    title = await db.get_manager_title(mid)
    admins = await db.list_manager_admins(mid)

    kb = InlineKeyboardBuilder()
    kb.button(text="➕ افزودن ادمین", callback_data=f"{P}mgr:admins_add:{mid}")
    for uid in admins[:30]:
        kb.button(text=f"➖ حذف {uid}", callback_data=f"{P}mgr:admins_rm:{mid}:{uid}")
    kb.button(text="⬅️ بازگشت", callback_data=f"{P}mgr:open:{mid}")
    kb.adjust(1)

    text = f"ادمین‌های مدیریت «{title}»:\n\n" + ("\n".join(map(str, admins)) if admins else "— خالی —")
    await cb.message.edit_text(text, reply_markup=kb.as_markup())
    await cb.answer()

@router.callback_query(F.data.startswith(P + "mgr:admins_add:"))
async def owner_mgr_admins_add_hint(cb: CallbackQuery):
    if not cb.from_user or not is_owner(cb.from_user.id):
        await cb.answer("دسترسی ندارید", show_alert=True)
        return
    mid = int(cb.data.split(":")[-1])
    await cb.message.answer(f"برای افزودن ادمین این مدیریت در PV بفرست:\n\n/mgradminadd {mid} 123456789")
    await cb.answer()

@router.message(Command("mgradminadd"))
async def owner_mgr_admins_add_cmd(message: Message):
    if not message.from_user or not is_owner(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer("فرمت: /mgradminadd <manager_chat_id> <user_id>")
        return
    mid = int(parts[1]); uid = int(parts[2])
    await db.add_manager_admin(mid, uid)
    await message.answer(f"✅ ادمین اضافه شد. mid={mid} uid={uid}")

@router.callback_query(F.data.startswith(P + "mgr:admins_rm:"))
async def owner_mgr_admins_rm(cb: CallbackQuery):
    if not cb.from_user or not is_owner(cb.from_user.id):
        await cb.answer("دسترسی ندارید", show_alert=True)
        return
    *_, mid_s, uid_s = cb.data.split(":")
    mid = int(mid_s); uid = int(uid_s)
    await db.remove_manager_admin(mid, uid)
    await cb.answer("حذف شد")
    # refresh
    await owner_mgr_admins(cb)



@router.callback_query(F.data.startswith(P + "unlink:approve:"))
async def owner_approve_unlink(cb: CallbackQuery):
    if not cb.from_user or not is_owner(cb.from_user.id):
        await cb.answer("دسترسی ندارید", show_alert=True)
        return

    req_id = int(cb.data.split(":")[-1])
    row = await db.get_unlink_request(req_id)
    if not row:
        await cb.answer("یافت نشد", show_alert=True)
        return

    _, mid, child_id, requested_by, _ = row

    await db.unlink_child(child_id)
    await db.set_unlink_request_status(req_id, "approved")

    mt = await db.get_manager_title(mid)
    ct = await db.get_group_title(child_id)
    await cb.message.edit_text(f"✅ «{ct}» از زیرمجموعه‌های «{mt}» حذف شد.")
    await cb.answer()


@router.callback_query(F.data.startswith(P + "unlink:deny:"))
async def owner_deny_unlink(cb: CallbackQuery):
    if not cb.from_user or not is_owner(cb.from_user.id):
        await cb.answer("دسترسی ندارید", show_alert=True)
        return

    req_id = int(cb.data.split(":")[-1])
    await db.set_unlink_request_status(req_id, "denied")
    await cb.message.edit_text("❌ درخواست رد شد.")
    await cb.answer()
