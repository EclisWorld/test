from aiogram import Dispatcher


def include_all_routers(dp: Dispatcher) -> None:
    """
    Central router registry.
    All feature routers must be imported here exactly once.
    This file is considered FINAL and should not be edited again.
    """

    try:
        from app.handlers.group_guard import router as group_guard_router
        dp.include_router(group_guard_router)
    except Exception:
        pass
