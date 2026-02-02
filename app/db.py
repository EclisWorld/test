# app/db.py
import aiosqlite
from typing import Optional, List, Tuple
from pathlib import Path


class Database:
    def __init__(self, path: str = "eclis_guard.sqlite3"):
        self.path = path
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> aiosqlite.Connection:
        # مهم: await نکن. این یک async context manager برمی‌گرداند که داخل async with await می‌شود.
        return aiosqlite.connect(self.path)

    async def _prepare(self, db: aiosqlite.Connection):
        # تنظیمات پیشنهادی برای sqlite در اپ async
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.execute("PRAGMA journal_mode = WAL;")
        await db.execute("PRAGMA synchronous = NORMAL;")

    async def init(self):
        async with self.connect() as db:
            await self._prepare(db)

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

            # safe list: chat_id NULL => GLOBAL safe
            await db.execute("""
                CREATE TABLE IF NOT EXISTS safe_users(
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NULL,
                    PRIMARY KEY (user_id, chat_id)
                )
            """)

            # bans: chat_id NULL => GLOBAL ban
            await db.execute("""
                CREATE TABLE IF NOT EXISTS bans(
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NULL,
                    PRIMARY KEY (user_id, chat_id)
                )
            """)

            # folders per chat
            await db.execute("""
                CREATE TABLE IF NOT EXISTS folders(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    UNIQUE(chat_id, name)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS folder_members(
                    folder_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    PRIMARY KEY(folder_id, user_id),
                    FOREIGN KEY(folder_id) REFERENCES folders(id) ON DELETE CASCADE
                )
            """)

            # stored links per chat (optional)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS links(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            await db.commit()

    # ---------- Admins ----------
    async def add_admin(self, user_id: int):
        async with self.connect() as db:
            await self._prepare(db)
            await db.execute("INSERT OR IGNORE INTO admins(user_id) VALUES (?)", (user_id,))
            await db.commit()

    async def is_admin(self, user_id: int) -> bool:
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,))
            row = await cur.fetchone()
            return row is not None

    async def list_admins(self) -> List[int]:
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute("SELECT user_id FROM admins ORDER BY user_id ASC")
            rows = await cur.fetchall()
            return [r[0] for r in rows]

    # ---------- Groups ----------
    async def upsert_group(self, chat_id: int, title: Optional[str], chat_type: str = "group"):
        async with self.connect() as db:
            await self._prepare(db)
            await db.execute(
                "INSERT INTO groups(chat_id,title,chat_type) VALUES (?,?,?) "
                "ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title, chat_type=excluded.chat_type",
                (chat_id, title, chat_type),
            )
            await db.commit()

    async def list_groups(self) -> List[Tuple[int, Optional[str], str]]:
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute("SELECT chat_id, title, chat_type FROM groups ORDER BY title ASC")
            return await cur.fetchall()

    # ---------- SAFE ----------
    async def add_safe(self, user_id: int, chat_id: Optional[int] = None):
        async with self.connect() as db:
            await self._prepare(db)
            await db.execute(
                "INSERT OR IGNORE INTO safe_users(user_id, chat_id) VALUES (?, ?)",
                (user_id, chat_id),
            )
            await db.commit()

    async def remove_safe(self, user_id: int, chat_id: Optional[int] = None):
        async with self.connect() as db:
            await self._prepare(db)
            await db.execute(
                "DELETE FROM safe_users WHERE user_id=? AND chat_id IS ?",
                (user_id, chat_id),
            )
            await db.commit()

    async def list_safe(self, chat_id: Optional[int] = None) -> List[int]:
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute(
                "SELECT user_id FROM safe_users WHERE chat_id IS ? ORDER BY user_id ASC",
                (chat_id,),
            )
            rows = await cur.fetchall()
            return [r[0] for r in rows]

    async def is_safe(self, user_id: int, chat_id: Optional[int] = None) -> bool:
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute(
                "SELECT 1 FROM safe_users WHERE user_id=? AND (chat_id IS ? OR chat_id IS NULL)",
                (user_id, chat_id),
            )
            row = await cur.fetchone()
            return row is not None

    # ---------- BANS ----------
    async def add_ban(self, user_id: int, chat_id: Optional[int] = None):
        async with self.connect() as db:
            await self._prepare(db)
            await db.execute(
                "INSERT OR IGNORE INTO bans(user_id, chat_id) VALUES (?, ?)",
                (user_id, chat_id),
            )
            await db.commit()

    async def remove_ban(self, user_id: int, chat_id: Optional[int] = None):
        async with self.connect() as db:
            await self._prepare(db)
            await db.execute(
                "DELETE FROM bans WHERE user_id=? AND chat_id IS ?",
                (user_id, chat_id),
            )
            await db.commit()

    async def list_bans(self, chat_id: Optional[int] = None) -> List[Tuple[int, Optional[int]]]:
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute(
                "SELECT user_id, chat_id FROM bans WHERE chat_id IS ? ORDER BY user_id ASC",
                (chat_id,),
            )
            return await cur.fetchall()

    async def is_banned(self, user_id: int, chat_id: Optional[int] = None) -> bool:
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute(
                "SELECT 1 FROM bans WHERE user_id=? AND (chat_id IS ? OR chat_id IS NULL)",
                (user_id, chat_id),
            )
            row = await cur.fetchone()
            return row is not None

    # ---------- Folders ----------
    async def create_folder(self, chat_id: int, name: str):
        async with self.connect() as db:
            await self._prepare(db)
            await db.execute(
                "INSERT OR IGNORE INTO folders(chat_id, name) VALUES (?,?)",
                (chat_id, name.strip()),
            )
            await db.commit()

    async def list_folders(self, chat_id: int) -> List[Tuple[int, str]]:
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute(
                "SELECT id, name FROM folders WHERE chat_id=? ORDER BY name ASC",
                (chat_id,),
            )
            return await cur.fetchall()

    async def folder_add_user(self, chat_id: int, folder_name: str, user_id: int):
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute(
                "SELECT id FROM folders WHERE chat_id=? AND name=?",
                (chat_id, folder_name),
            )
            row = await cur.fetchone()
            if not row:
                return False
            folder_id = row[0]
            await db.execute(
                "INSERT OR IGNORE INTO folder_members(folder_id, user_id) VALUES (?,?)",
                (folder_id, user_id),
            )
            await db.commit()
            return True

    async def folder_remove_user(self, chat_id: int, folder_name: str, user_id: int):
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute(
                "SELECT id FROM folders WHERE chat_id=? AND name=?",
                (chat_id, folder_name),
            )
            row = await cur.fetchone()
            if not row:
                return False
            folder_id = row[0]
            await db.execute(
                "DELETE FROM folder_members WHERE folder_id=? AND user_id=?",
                (folder_id, user_id),
            )
            await db.commit()
            return True

    async def list_folder_members(self, chat_id: int, folder_name: str) -> List[int]:
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute(
                "SELECT fm.user_id FROM folder_members fm "
                "JOIN folders f ON f.id=fm.folder_id "
                "WHERE f.chat_id=? AND f.name=? "
                "ORDER BY fm.user_id ASC",
                (chat_id, folder_name),
            )
            rows = await cur.fetchall()
            return [r[0] for r in rows]

    # ---------- Links ----------
    async def add_link(self, chat_id: int, name: str, url: str):
        async with self.connect() as db:
            await self._prepare(db)
            await db.execute(
                "INSERT INTO links(chat_id,name,url) VALUES (?,?,?)",
                (chat_id, name.strip(), url.strip()),
            )
            await db.commit()

    async def list_links(self, chat_id: int) -> List[Tuple[int, str, str, str]]:
        async with self.connect() as db:
            await self._prepare(db)
            cur = await db.execute(
                "SELECT id, name, url, created_at FROM links WHERE chat_id=? ORDER BY id DESC",
                (chat_id,),
            )
            return await cur.fetchall()

    async def delete_link(self, link_id: int):
        async with self.connect() as db:
            await self._prepare(db)
            await db.execute("DELETE FROM links WHERE id=?", (link_id,))
            await db.commit()

    # ---------- Clone (copy settings from src_chat to dst_chat) ----------
    async def clone_group_data(self, src_chat_id: int, dst_chat_id: int):
        async with self.connect() as db:
            await self._prepare(db)

            # safe (group-specific only)
            await db.execute(
                "INSERT OR IGNORE INTO safe_users(user_id, chat_id) "
                "SELECT user_id, ? FROM safe_users WHERE chat_id=?",
                (dst_chat_id, src_chat_id),
            )

            # bans (group-specific only)
            await db.execute(
                "INSERT OR IGNORE INTO bans(user_id, chat_id) "
                "SELECT user_id, ? FROM bans WHERE chat_id=?",
                (dst_chat_id, src_chat_id),
            )

            # folders + members
            cur = await db.execute("SELECT name FROM folders WHERE chat_id=?", (src_chat_id,))
            folder_names = [r[0] for r in await cur.fetchall()]
            for fname in folder_names:
                await db.execute(
                    "INSERT OR IGNORE INTO folders(chat_id,name) VALUES (?,?)",
                    (dst_chat_id, fname),
                )

                cur2 = await db.execute(
                    "SELECT fm.user_id FROM folder_members fm "
                    "JOIN folders f ON f.id=fm.folder_id "
                    "WHERE f.chat_id=? AND f.name=?",
                    (src_chat_id, fname),
                )
                users = [r[0] for r in await cur2.fetchall()]

                cur3 = await db.execute(
                    "SELECT id FROM folders WHERE chat_id=? AND name=?",
                    (dst_chat_id, fname),
                )
                row3 = await cur3.fetchone()
                if row3:
                    dst_folder_id = row3[0]
                    for uid in users:
                        await db.execute(
                            "INSERT OR IGNORE INTO folder_members(folder_id,user_id) VALUES (?,?)",
                            (dst_folder_id, uid),
                        )

            # links (copy)
            await db.execute(
                "INSERT INTO links(chat_id,name,url) "
                "SELECT ?, name, url FROM links WHERE chat_id=?",
                (dst_chat_id, src_chat_id),
            )

            await db.commit()


db = Database()
