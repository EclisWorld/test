from aiogram.fsm.state import StatesGroup, State


class OwnerStates(StatesGroup):
    waiting_for_admin_id = State()
    waiting_for_clone_target_ids = State()
    waiting_for_set_context_chat_id = State()


class AdminStates(StatesGroup):
    waiting_for_safe_user_id = State()
    waiting_for_remove_safe_user_id = State()
    waiting_for_set_context_chat_id = State()
    waiting_for_create_folder_name = State()
    waiting_for_folder_add_user_id = State()
    waiting_for_folder_remove_user_id = State()
