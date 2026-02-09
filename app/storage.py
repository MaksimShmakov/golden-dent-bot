import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


@dataclass
class PendingComment:
    user_id: int
    username: str
    created_at: str


class SQLiteStateStore:
    def __init__(self, data_dir: str) -> None:
        self._path = Path(data_dir) / "state.sqlite"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_comment (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_map (
                    username TEXT PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def set_pending(self, user_id: int, username: str, created_at: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pending_comment (user_id, username, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username=excluded.username,
                    created_at=excluded.created_at
                """,
                (user_id, username, created_at.isoformat()),
            )
            conn.commit()

    def pop_pending(self, user_id: int) -> PendingComment | None:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT user_id, username, created_at FROM pending_comment WHERE user_id=?",
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            conn.execute("DELETE FROM pending_comment WHERE user_id=?", (user_id,))
            conn.commit()
        return PendingComment(user_id=row[0], username=row[1], created_at=row[2])

    def list_pending(self) -> Iterable[PendingComment]:
        with self._connect() as conn:
            cur = conn.execute("SELECT user_id, username, created_at FROM pending_comment")
            rows = cur.fetchall()
        return [PendingComment(user_id=row[0], username=row[1], created_at=row[2]) for row in rows]

    def upsert_user(self, username: str, chat_id: int, updated_at: datetime) -> None:
        normalized = _normalize_username(username)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_map (username, chat_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    chat_id=excluded.chat_id,
                    updated_at=excluded.updated_at
                """,
                (normalized, chat_id, updated_at.isoformat()),
            )
            conn.commit()

    def get_chat_id(self, username: str) -> int | None:
        normalized = _normalize_username(username)
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT chat_id FROM user_map WHERE username=?",
                (normalized,),
            )
            row = cur.fetchone()
        return row[0] if row else None


def _normalize_username(username: str) -> str:
    username = username.strip()
    if not username:
        return ""
    if not username.startswith("@"):
        username = f"@{username}"
    return username.lower()
