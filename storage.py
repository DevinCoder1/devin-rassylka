"""SQLite storage for per-user configuration, chats and stats."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import aiosqlite

from config import DB_PATH, DEFAULT_CYCLE_DELAY, DEFAULT_INTERVAL, DEFAULT_JITTER


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_user_id INTEGER PRIMARY KEY,
    api_id INTEGER,
    api_hash TEXT,
    phone TEXT,
    session TEXT,
    message_text TEXT DEFAULT '',
    media_path TEXT,
    media_type TEXT,
    interval INTEGER DEFAULT 30,
    jitter INTEGER DEFAULT 0,
    cycle_delay INTEGER DEFAULT 0,
    spintax_enabled INTEGER DEFAULT 1,
    shuffle INTEGER DEFAULT 0,
    is_running INTEGER DEFAULT 0,
    sent_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS chats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    identifier TEXT NOT NULL,
    title TEXT,
    UNIQUE(user_id, identifier)
);
"""


@dataclass
class UserRow:
    tg_user_id: int
    api_id: Optional[int]
    api_hash: Optional[str]
    phone: Optional[str]
    session: Optional[str]
    message_text: str
    media_path: Optional[str]
    media_type: Optional[str]
    interval: int
    jitter: int
    cycle_delay: int
    spintax_enabled: bool
    shuffle: bool
    is_running: bool
    sent_count: int
    fail_count: int


@dataclass
class ChatRow:
    id: int
    user_id: int
    identifier: str
    title: Optional[str]


class Storage:
    def __init__(self, path: str = DB_PATH) -> None:
        self.path = path

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(SCHEMA)
            # Lightweight migrations for older databases.
            cursor = await db.execute("PRAGMA table_info(users)")
            cols = {row[1] for row in await cursor.fetchall()}
            if "media_path" not in cols:
                await db.execute("ALTER TABLE users ADD COLUMN media_path TEXT")
            if "media_type" not in cols:
                await db.execute("ALTER TABLE users ADD COLUMN media_type TEXT")
            await db.commit()

    async def _ensure_user(self, db: aiosqlite.Connection, tg_user_id: int) -> None:
        await db.execute(
            "INSERT OR IGNORE INTO users (tg_user_id, interval, jitter, cycle_delay) "
            "VALUES (?, ?, ?, ?)",
            (tg_user_id, DEFAULT_INTERVAL, DEFAULT_JITTER, DEFAULT_CYCLE_DELAY),
        )

    async def get_user(self, tg_user_id: int) -> UserRow:
        async with aiosqlite.connect(self.path) as db:
            await self._ensure_user(db, tg_user_id)
            await db.commit()
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM users WHERE tg_user_id = ?", (tg_user_id,)
            )
            row = await cursor.fetchone()
            assert row is not None
            return UserRow(
                tg_user_id=row["tg_user_id"],
                api_id=row["api_id"],
                api_hash=row["api_hash"],
                phone=row["phone"],
                session=row["session"],
                message_text=row["message_text"] or "",
                media_path=row["media_path"],
                media_type=row["media_type"],
                interval=row["interval"],
                jitter=row["jitter"],
                cycle_delay=row["cycle_delay"],
                spintax_enabled=bool(row["spintax_enabled"]),
                shuffle=bool(row["shuffle"]),
                is_running=bool(row["is_running"]),
                sent_count=row["sent_count"],
                fail_count=row["fail_count"],
            )

    async def update_user(self, tg_user_id: int, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [tg_user_id]
        async with aiosqlite.connect(self.path) as db:
            await self._ensure_user(db, tg_user_id)
            await db.execute(f"UPDATE users SET {cols} WHERE tg_user_id = ?", values)
            await db.commit()

    async def inc_counters(self, tg_user_id: int, sent: int = 0, failed: int = 0) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE users SET sent_count = sent_count + ?, fail_count = fail_count + ? "
                "WHERE tg_user_id = ?",
                (sent, failed, tg_user_id),
            )
            await db.commit()

    async def reset_stats(self, tg_user_id: int) -> None:
        await self.update_user(tg_user_id, sent_count=0, fail_count=0)

    async def add_chat(self, tg_user_id: int, identifier: str, title: Optional[str]) -> bool:
        async with aiosqlite.connect(self.path) as db:
            await self._ensure_user(db, tg_user_id)
            try:
                await db.execute(
                    "INSERT INTO chats (user_id, identifier, title) VALUES (?, ?, ?)",
                    (tg_user_id, identifier, title),
                )
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False

    async def remove_chat(self, tg_user_id: int, chat_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "DELETE FROM chats WHERE id = ? AND user_id = ?", (chat_id, tg_user_id)
            )
            await db.commit()

    async def list_chats(self, tg_user_id: int) -> list[ChatRow]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM chats WHERE user_id = ? ORDER BY id", (tg_user_id,)
            )
            rows = await cursor.fetchall()
            return [
                ChatRow(id=r["id"], user_id=r["user_id"], identifier=r["identifier"], title=r["title"])
                for r in rows
            ]

    async def list_running_users(self) -> list[int]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT tg_user_id FROM users WHERE is_running = 1 AND session IS NOT NULL"
            )
            rows = await cursor.fetchall()
            return [r[0] for r in rows]
