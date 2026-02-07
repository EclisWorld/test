# app/db.py
from __future__ import annotations

import aiosqlite
from pathlib import Path
from typing import Optional, List, Tuple


class Database:
    def __init__(self, path: str = "eclis_guard.sqlite3"):
        self.path = path
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> aiosqlite.Connection:
        return aiosqlite.connect(self.path)

    async def _prepare(self, db: aiosqlite.Connection):
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.execute("PRAGMA journal_mode = WAL;")
        await db.execute("PRAGMA synchronous = NORMAL;")

    async def init(self):
        async with self.connect() as db:
            await self._prepare(db)

            # ----- app settings (hub, etc.) -----
            await db.execute("""
                CREATE TABLE IF NOT EXISTS app_settings(
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            # ----- core -----
            await db.execute("""
                CREATE TABLE IF NOT EXISTS admins(
                    user_id INTEGER PRIMARY KEY
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS groups(
                    chat_id INTEGER PRIMARY KEY,
                    title TEXT,
                    chat_type TEXT DEFAULT 'group'
                )
            """)

            # chat_id NULL => GLOBAL safe
            await db.execute("""
                CREATE TABLE IF NOT EXISTS safe_users(
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NULL,
                    PRIMARY KEY (user_id, chat_id)
                )
            """)

            # chat_id NULL => GLOBAL ban
            await db.execute("""
                CREATE TABLE IF NOT EXISTS bans(
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NULL,
                    PRIMARY KEY (user_id, chat_id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS group_settings(
                    chat_id INTEGER PRIMARY KEY,
                    guard_enabled INTEGER NOT NULL DEFAULT 0
                )
            """)

            # ----- manager system -----
            await db.execute("""
                CREATE TABLE IF NOT EXISTS manager_groups(
                    manager_chat_id INTEGER PRIMARY KEY,
                    title TEXT,
                    child_limit INTEGER NOT NULL DEFAULT 0
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS manager_admins(
                    manager_chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    PRIMARY KEY(manager_chat_id, user_id),
                    FOREIGN KEY(manager_chat_id) REFERENCES manager_groups(manager_chat_id) ON DELETE CASCADE
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS group_links(
                    child_chat_id INTEGER PRIMARY KEY,
                    manager_chat_id INTEGER NOT NULL,
                    linked_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(manager_chat_id) REFERENCES manager_groups(manager_chat_id) ON DELETE CASCADE
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS unlink_requests(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    manager_chat_id INTEGER NOT NULL,
                    child_chat_id INTEGER NOT NULL,
                    requested_by INTEGER NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    status TEXT NOT NULL DEFAULT 'pending'
                )
            """)

            await db.commit()

    # =========================
    # App settings (Hub)
    # =========================
    async def set_setting(self, key: str, value: str) -> None:
        async with self.connect() as db:
            await self._prepare(db)
            await db.execute(
                "INSERT INTO app_settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            await db.commit()

    async def get_setting(self, key: str) -> Optional[str]:
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute("SELECT value FROM app_settings WHERE key=? LIMIT 1", (key,))
            row = await cur.fetchone()
            return str(row[0]) if row and row[0] is not None else None

    async def hub_get(self) -> Optional[int]:
        v = await self.get_setting("hub_chat_id")
        try:
            return int(v) if v is not None else None
        except Exception:
            return None

    async def hub_set_once(self, chat_id: int) -> Tuple[bool, str]:
        """
        فقط یک هاب گلوبال داریم.
        اگر قبلاً ست شده باشد، دوباره ست نمی‌شود مگر اینکه hub_clear شود.
        """
        cur = await self.hub_get()
        if cur and int(cur) != 0:
            return False, f"هاب قبلاً فعال شده: {cur}"
        await self.set_setting("hub_chat_id", str(int(chat_id)))
        return True, "هاب ثبت شد."

    async def hub_clear(self, chat_id: int) -> Tuple[bool, str]:
        cur = await self.hub_get()
        if not cur:
            return False, "هاب فعلاً فعال نیست."
        if int(cur) != int(chat_id):
            return False, f"هاب روی گروه دیگری است: {cur}"
        await self.set_setting("hub_chat_id", "0")
        return True, "هاب خاموش شد."

    # =========================
    # Guard enable/disable
    # =========================
    async def set_guard_enabled(self, chat_id: int, enabled: bool) -> None:
        async with self.connect() as db:
            await self._prepare(db)
            await db.execute(
                """
                INSERT INTO group_settings(chat_id, guard_enabled)
                VALUES(?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET guard_enabled=excluded.guard_enabled
                """,
                (int(chat_id), 1 if enabled else 0),
            )
            await db.commit()

    async def is_guard_enabled(self, chat_id: int) -> bool:
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute(
                "SELECT guard_enabled FROM group_settings WHERE chat_id=? LIMIT 1",
                (int(chat_id),),
            )
            row = await cur.fetchone()
            return bool(row and int(row[0]) == 1)

    # =========================
    # Admins (legacy/global)
    # =========================
    async def add_admin(self, user_id: int) -> None:
        async with self.connect() as db:
            await self._prepare(db)
            await db.execute("INSERT OR IGNORE INTO admins(user_id) VALUES (?)", (int(user_id),))
            await db.commit()

    async def is_admin(self, user_id: int) -> bool:
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute("SELECT 1 FROM admins WHERE user_id=? LIMIT 1", (int(user_id),))
            return (await cur.fetchone()) is not None

    async def list_admins(self) -> List[int]:
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute("SELECT user_id FROM admins ORDER BY user_id ASC")
            rows = await cur.fetchall()
            return [int(r[0]) for r in rows]

    # =========================
    # Groups
    # =========================
    async def upsert_group(self, chat_id: int, title: Optional[str], chat_type: str = "group") -> None:
        async with self.connect() as db:
            await self._prepare(db)
            await db.execute(
                "INSERT INTO groups(chat_id,title,chat_type) VALUES (?,?,?) "
                "ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title, chat_type=excluded.chat_type",
                (int(chat_id), title, chat_type),
            )
            await db.commit()

    async def list_groups(self) -> List[Tuple[int, Optional[str], str]]:
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute("SELECT chat_id, title, chat_type FROM groups ORDER BY COALESCE(title,'') ASC")
            rows = await cur.fetchall()
            return [(int(r[0]), r[1], r[2]) for r in rows]

    async def get_group_title(self, chat_id: int) -> str:
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute("SELECT title FROM groups WHERE chat_id=? LIMIT 1", (int(chat_id),))
            row = await cur.fetchone()
            if row and row[0]:
                return str(row[0])
            return str(int(chat_id))

    # =========================
    # Manager groups
    # =========================
    async def list_manager_groups(self) -> List[Tuple[int, Optional[str], int]]:
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute(
                "SELECT manager_chat_id, title, child_limit FROM manager_groups ORDER BY manager_chat_id DESC"
            )
            rows = await cur.fetchall()
            return [(int(r[0]), r[1], int(r[2])) for r in rows]

    async def upsert_manager_group(self, manager_chat_id: int, title: Optional[str] = None) -> None:
        async with self.connect() as db:
            await self._prepare(db)
            await db.execute(
                """
                INSERT INTO manager_groups(manager_chat_id, title)
                VALUES(?, ?)
                ON CONFLICT(manager_chat_id) DO UPDATE SET title=excluded.title
                """,
                (int(manager_chat_id), title),
            )
            await db.commit()

    async def get_manager_title(self, manager_chat_id: int) -> str:
        mid = int(manager_chat_id)
        async with self.connect() as db:
            await self._prepare(db)

            cur = await db.execute(
                "SELECT title FROM manager_groups WHERE manager_chat_id=? LIMIT 1",
                (mid,),
            )
            row = await cur.fetchone()
            if row and row[0]:
                return str(row[0])

            cur = await db.execute(
                "SELECT title FROM groups WHERE chat_id=? LIMIT 1",
                (mid,),
            )
            row = await cur.fetchone()
            if row and row[0]:
                return str(row[0])

            return str(mid)

    async def get_manager_limit(self, manager_chat_id: int) -> int:
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute(
                "SELECT child_limit FROM manager_groups WHERE manager_chat_id=? LIMIT 1",
                (int(manager_chat_id),),
            )
            row = await cur.fetchone()
            return int(row[0]) if row and row[0] is not None else 0

    async def set_manager_limit(self, manager_chat_id: int, child_limit: int) -> None:
        async with self.connect() as db:
            await self._prepare(db)
            await db.execute(
                """
                INSERT INTO manager_groups(manager_chat_id, child_limit)
                VALUES(?, ?)
                ON CONFLICT(manager_chat_id) DO UPDATE SET child_limit=excluded.child_limit
                """,
                (int(manager_chat_id), int(child_limit)),
            )
            await db.commit()

    async def add_manager_admin(self, manager_chat_id: int, user_id: int) -> None:
        async with self.connect() as db:
            await self._prepare(db)
            await db.execute(
                "INSERT OR IGNORE INTO manager_admins(manager_chat_id, user_id) VALUES(?, ?)",
                (int(manager_chat_id), int(user_id)),
            )
            await db.commit()

    async def remove_manager_admin(self, manager_chat_id: int, user_id: int) -> None:
        async with self.connect() as db:
            await self._prepare(db)
            await db.execute(
                "DELETE FROM manager_admins WHERE manager_chat_id=? AND user_id=?",
                (int(manager_chat_id), int(user_id)),
            )
            await db.commit()

    async def is_manager_admin(self, manager_chat_id: int, user_id: int) -> bool:
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute(
                "SELECT 1 FROM manager_admins WHERE manager_chat_id=? AND user_id=? LIMIT 1",
                (int(manager_chat_id), int(user_id)),
            )
            return (await cur.fetchone()) is not None

    async def list_managers_for_admin(self, user_id: int) -> List[int]:
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute(
                "SELECT manager_chat_id FROM manager_admins WHERE user_id=? ORDER BY manager_chat_id DESC",
                (int(user_id),),
            )
            rows = await cur.fetchall()
            return [int(r[0]) for r in rows]

    # =========================
    # Links (child -> manager)
    # =========================
    async def list_children(self, manager_chat_id: int) -> List[int]:
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute(
                "SELECT child_chat_id FROM group_links WHERE manager_chat_id=? ORDER BY linked_at DESC",
                (int(manager_chat_id),),
            )
            rows = await cur.fetchall()
            return [int(r[0]) for r in rows]

    async def get_manager_for_child(self, child_chat_id: int) -> Optional[int]:
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute(
                "SELECT manager_chat_id FROM group_links WHERE child_chat_id=? LIMIT 1",
                (int(child_chat_id),),
            )
            row = await cur.fetchone()
            return int(row[0]) if row and row[0] is not None else None

    async def resolve_effective_chat_id(self, chat_id: int) -> int:
        """
        If chat_id is a child in group_links -> return manager_chat_id
        If chat_id itself is a manager group -> return itself
        Else -> return chat_id
        """
        cid = int(chat_id)
        async with self.connect() as db:
            await self._prepare(db)

            cur = await db.execute(
                "SELECT manager_chat_id FROM group_links WHERE child_chat_id=? LIMIT 1",
                (cid,),
            )
            row = await cur.fetchone()
            if row and row[0] is not None:
                return int(row[0])

            cur = await db.execute(
                "SELECT 1 FROM manager_groups WHERE manager_chat_id=? LIMIT 1",
                (cid,),
            )
            if (await cur.fetchone()) is not None:
                return cid

            return cid

    async def get_scope_chats_for_manager(self, manager_chat_id: int) -> List[int]:
        """
        scope = manager + همه child ها
        """
        mid = int(manager_chat_id)
        children = await self.list_children(mid)
        # اول manager بعد بچه‌ها
        out = [mid]
        for c in children:
            if c not in out:
                out.append(c)
        return out
    
    async def count_children(self, manager_chat_id: int) -> int:
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute(
                "SELECT COUNT(1) FROM group_links WHERE manager_chat_id=?",
                (int(manager_chat_id),),
            )
            row = await cur.fetchone()
            return int(row[0]) if row and row[0] is not None else 0

    async def link_child(self, manager_chat_id: int, child_chat_id: int) -> Tuple[bool, str]:
        mid = int(manager_chat_id)
        cid = int(child_chat_id)

        # manager باید وجود داشته باشد
        async with self.connect() as db:
            await self._prepare(db)

            cur = await db.execute("SELECT 1 FROM manager_groups WHERE manager_chat_id=? LIMIT 1", (mid,))
            if (await cur.fetchone()) is None:
                return False, "این Management در DB ثبت نشده."

            # limit
            limit = await self.get_manager_limit(mid)
            if limit and limit > 0:
                cnt = await self.count_children(mid)
                if cnt >= limit:
                    return False, f"به سقف زیرمجموعه رسیدی (limit={limit})."

            # child قبلاً لینک شده؟
            cur = await db.execute("SELECT manager_chat_id FROM group_links WHERE child_chat_id=? LIMIT 1", (cid,))
            row = await cur.fetchone()
            if row and row[0] is not None:
                old = int(row[0])
                if old == mid:
                    return True, "این گروه از قبل زیرمجموعه همین Management بوده."
                return False, f"این گروه قبلاً زیرمجموعه Management دیگری است: {old}"

            await db.execute(
                "INSERT INTO group_links(child_chat_id, manager_chat_id) VALUES(?, ?)",
                (cid, mid),
            )
            await db.commit()
            return True, "زیرمجموعه لینک شد."

    async def unlink_child(self, child_chat_id: int) -> Tuple[bool, str]:
        cid = int(child_chat_id)
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute("SELECT 1 FROM group_links WHERE child_chat_id=? LIMIT 1", (cid,))
            if (await cur.fetchone()) is None:
                return False, "این گروه زیرمجموعه هیچ Managementی نیست."
            await db.execute("DELETE FROM group_links WHERE child_chat_id=?", (cid,))
            await db.commit()
            return True, "unlink انجام شد."


    # =========================
    # SAFE
    # =========================
    async def add_safe(self, user_id: int, chat_id: Optional[int] = None) -> None:
        async with self.connect() as db:
            await self._prepare(db)
            await db.execute(
                "INSERT OR IGNORE INTO safe_users(user_id, chat_id) VALUES (?, ?)",
                (int(user_id), int(chat_id) if chat_id is not None else None),
            )
            await db.commit()

    async def remove_safe(self, user_id: int, chat_id: Optional[int] = None) -> None:
        async with self.connect() as db:
            await self._prepare(db)
            await db.execute(
                "DELETE FROM safe_users WHERE user_id=? AND chat_id IS ?",
                (int(user_id), int(chat_id) if chat_id is not None else None),
            )
            await db.commit()

    async def list_safe(self, chat_id: Optional[int] = None) -> List[int]:
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute(
                "SELECT user_id FROM safe_users WHERE chat_id IS ? ORDER BY user_id ASC",
                (int(chat_id) if chat_id is not None else None,),
            )
            rows = await cur.fetchall()
            return [int(r[0]) for r in rows]

    async def is_safe(self, user_id: int, chat_id: Optional[int] = None) -> bool:
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute(
                "SELECT 1 FROM safe_users WHERE user_id=? AND (chat_id IS ? OR chat_id IS NULL) LIMIT 1",
                (int(user_id), int(chat_id) if chat_id is not None else None),
            )
            return (await cur.fetchone()) is not None

    # =========================
    # BANS
    # =========================
    async def add_ban(self, user_id: int, chat_id: Optional[int] = None) -> None:
        async with self.connect() as db:
            await self._prepare(db)
            await db.execute(
                "INSERT OR IGNORE INTO bans(user_id, chat_id) VALUES (?, ?)",
                (int(user_id), int(chat_id) if chat_id is not None else None),
            )
            await db.commit()

    async def remove_ban(self, user_id: int, chat_id: Optional[int] = None) -> None:
        async with self.connect() as db:
            await self._prepare(db)
            await db.execute(
                "DELETE FROM bans WHERE user_id=? AND chat_id IS ?",
                (int(user_id), int(chat_id) if chat_id is not None else None),
            )
            await db.commit()

    async def list_bans(self, chat_id: Optional[int] = None) -> List[Tuple[int, Optional[int]]]:
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute(
                "SELECT user_id, chat_id FROM bans WHERE chat_id IS ? ORDER BY user_id ASC",
                (int(chat_id) if chat_id is not None else None,),
            )
            rows = await cur.fetchall()
            return [(int(r[0]), r[1]) for r in rows]

    async def is_banned(self, user_id: int, chat_id: Optional[int] = None) -> bool:
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute(
                "SELECT 1 FROM bans WHERE user_id=? AND (chat_id IS ? OR chat_id IS NULL) LIMIT 1",
                (int(user_id), int(chat_id) if chat_id is not None else None),
            )
            return (await cur.fetchone()) is not None


db = Database()
