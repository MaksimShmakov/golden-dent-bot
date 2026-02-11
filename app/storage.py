import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS client_map (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_activation (
                    user_id INTEGER PRIMARY KEY,
                    activated_at TEXT NOT NULL
                )
                """
            )
            self._migrate_clients_from_user_map(conn)
            conn.commit()

    def _migrate_clients_from_user_map(self, conn: sqlite3.Connection) -> None:
        cur = conn.execute(
            "SELECT chat_id, username, updated_at FROM user_map ORDER BY updated_at"
        )
        for chat_id, username, updated_at in cur.fetchall():
            conn.execute(
                """
                INSERT INTO client_map (user_id, username, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username=excluded.username,
                    updated_at=excluded.updated_at
                """,
                (chat_id, username, updated_at),
            )

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
        return [
            PendingComment(user_id=row[0], username=row[1], created_at=row[2])
            for row in rows
        ]

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

    def upsert_client(self, user_id: int, username: str, updated_at: datetime) -> bool:
        normalized = _normalize_username(username)
        if not normalized:
            return False
        with self._connect() as conn:
            cur = conn.execute("SELECT username FROM client_map WHERE user_id=?", (user_id,))
            row = cur.fetchone()
            changed = not row or row[0] != normalized
            conn.execute(
                """
                INSERT INTO client_map (user_id, username, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username=excluded.username,
                    updated_at=excluded.updated_at
                """,
                (user_id, normalized, updated_at.isoformat()),
            )
            conn.commit()
        return changed

    def remove_client(self, user_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM client_map WHERE user_id=?", (user_id,))
            conn.commit()
        return cur.rowcount > 0

    def list_client_usernames(self) -> list[str]:
        with self._connect() as conn:
            cur = conn.execute("SELECT username FROM client_map ORDER BY username")
            rows = cur.fetchall()
        return [row[0] for row in rows]

    def mark_activated(self, user_id: int, activated_at: datetime) -> bool:
        with self._connect() as conn:
            cur = conn.execute("SELECT 1 FROM user_activation WHERE user_id=?", (user_id,))
            exists = cur.fetchone() is not None
            if exists:
                return False
            conn.execute(
                "INSERT INTO user_activation (user_id, activated_at) VALUES (?, ?)",
                (user_id, activated_at.isoformat()),
            )
            conn.commit()
        return True

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
