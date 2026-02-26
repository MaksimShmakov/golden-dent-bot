from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class PendingAction:
    user_id: int
    username: str
    action_type: str
    appointment_row: int | None
    status_column: str
    created_at: str


@dataclass
class ClientProfile:
    user_id: int
    username: str
    full_name: str
    phone: str
    updated_at: str


@dataclass
class UndeliveredEvent:
    id: int
    created_at: str
    username: str
    kind: str
    reason: str
    exported_at: str | None


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
                    action_type TEXT NOT NULL DEFAULT 'not_ready_comment',
                    appointment_row INTEGER,
                    status_column TEXT NOT NULL DEFAULT 'C',
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
                    username TEXT NOT NULL DEFAULT '',
                    full_name TEXT NOT NULL DEFAULT '',
                    phone TEXT NOT NULL DEFAULT '',
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS undelivered_event (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    username TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    exported_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reminder_context (
                    chat_id INTEGER PRIMARY KEY,
                    appointment_row INTEGER NOT NULL,
                    status_column TEXT NOT NULL DEFAULT 'C',
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._migrate_pending_comment_schema(conn)
            self._migrate_client_map_schema(conn)
            self._migrate_reminder_context_schema(conn)
            self._migrate_clients_from_user_map(conn)
            conn.commit()

    def _migrate_pending_comment_schema(self, conn: sqlite3.Connection) -> None:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(pending_comment)").fetchall()
        }
        if "action_type" not in columns:
            conn.execute(
                "ALTER TABLE pending_comment "
                "ADD COLUMN action_type TEXT NOT NULL DEFAULT 'not_ready_comment'"
            )
        if "appointment_row" not in columns:
            conn.execute("ALTER TABLE pending_comment ADD COLUMN appointment_row INTEGER")
        if "status_column" not in columns:
            conn.execute(
                "ALTER TABLE pending_comment ADD COLUMN status_column TEXT NOT NULL DEFAULT 'C'"
            )

    def _migrate_client_map_schema(self, conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(client_map)").fetchall()}
        if "full_name" not in columns:
            conn.execute("ALTER TABLE client_map ADD COLUMN full_name TEXT NOT NULL DEFAULT ''")
        if "phone" not in columns:
            conn.execute("ALTER TABLE client_map ADD COLUMN phone TEXT NOT NULL DEFAULT ''")

    def _migrate_reminder_context_schema(self, conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(reminder_context)").fetchall()}
        if "status_column" not in columns:
            conn.execute(
                "ALTER TABLE reminder_context ADD COLUMN status_column TEXT NOT NULL DEFAULT 'C'"
            )

    def _migrate_clients_from_user_map(self, conn: sqlite3.Connection) -> None:
        cur = conn.execute(
            "SELECT chat_id, username, updated_at FROM user_map ORDER BY updated_at"
        )
        for chat_id, username, updated_at in cur.fetchall():
            conn.execute(
                """
                INSERT INTO client_map (user_id, username, full_name, phone, updated_at)
                VALUES (?, ?, '', '', ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username=excluded.username,
                    updated_at=excluded.updated_at
                """,
                (chat_id, username, updated_at),
            )

    def set_pending(
        self,
        user_id: int,
        username: str,
        created_at: datetime,
        action_type: str = "not_ready_comment",
        appointment_row: int | None = None,
        status_column: str = "C",
    ) -> None:
        normalized_status_column = _normalize_status_column(status_column)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pending_comment (
                    user_id,
                    username,
                    action_type,
                    appointment_row,
                    status_column,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username=excluded.username,
                    action_type=excluded.action_type,
                    appointment_row=excluded.appointment_row,
                    status_column=excluded.status_column,
                    created_at=excluded.created_at
                """,
                (
                    user_id,
                    username,
                    action_type,
                    appointment_row,
                    normalized_status_column,
                    created_at.isoformat(),
                ),
            )
            conn.commit()

    def pop_pending(self, user_id: int) -> PendingAction | None:
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT user_id, username, action_type, appointment_row, status_column, created_at
                FROM pending_comment
                WHERE user_id=?
                """,
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            conn.execute("DELETE FROM pending_comment WHERE user_id=?", (user_id,))
            conn.commit()
        return PendingAction(
            user_id=row[0],
            username=row[1],
            action_type=row[2],
            appointment_row=row[3],
            status_column=row[4],
            created_at=row[5],
        )

    def list_pending(self) -> Iterable[PendingAction]:
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT user_id, username, action_type, appointment_row, status_column, created_at
                FROM pending_comment
                ORDER BY created_at
                """
            )
            rows = cur.fetchall()
        return [
            PendingAction(
                user_id=row[0],
                username=row[1],
                action_type=row[2],
                appointment_row=row[3],
                status_column=row[4],
                created_at=row[5],
            )
            for row in rows
        ]

    def upsert_user(self, username: str, chat_id: int, updated_at: datetime) -> None:
        normalized = _normalize_username(username)
        if not normalized:
            return
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

    def upsert_client(
        self,
        user_id: int,
        username: str | None,
        full_name: str | None,
        phone: str | None,
        updated_at: datetime,
    ) -> bool:
        normalized_username = _normalize_username(username)
        normalized_full_name = _normalize_full_name(full_name)
        normalized_phone = _normalize_phone(phone)
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT username, full_name, phone FROM client_map WHERE user_id=?",
                (user_id,),
            )
            row = cur.fetchone()
            changed = not row or row != (
                normalized_username,
                normalized_full_name,
                normalized_phone,
            )
            conn.execute(
                """
                INSERT INTO client_map (user_id, username, full_name, phone, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username=excluded.username,
                    full_name=excluded.full_name,
                    phone=excluded.phone,
                    updated_at=excluded.updated_at
                """,
                (
                    user_id,
                    normalized_username,
                    normalized_full_name,
                    normalized_phone,
                    updated_at.isoformat(),
                ),
            )
            conn.commit()
        return changed

    def update_client_phone(self, user_id: int, phone: str | None, updated_at: datetime) -> bool:
        normalized_phone = _normalize_phone(phone)
        with self._connect() as conn:
            cur = conn.execute("SELECT phone FROM client_map WHERE user_id=?", (user_id,))
            row = cur.fetchone()
            if not row:
                return False
            changed = row[0] != normalized_phone
            conn.execute(
                """
                UPDATE client_map
                SET phone=?, updated_at=?
                WHERE user_id=?
                """,
                (normalized_phone, updated_at.isoformat(), user_id),
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
            cur = conn.execute(
                "SELECT username FROM client_map WHERE username != '' ORDER BY username"
            )
            rows = cur.fetchall()
        return [row[0] for row in rows]

    def list_clients(self) -> list[ClientProfile]:
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT user_id, username, full_name, phone, updated_at
                FROM client_map
                ORDER BY
                    CASE WHEN username = '' THEN 1 ELSE 0 END,
                    username,
                    user_id
                """
            )
            rows = cur.fetchall()
        return [
            ClientProfile(
                user_id=row[0],
                username=row[1],
                full_name=row[2],
                phone=row[3],
                updated_at=row[4],
            )
            for row in rows
        ]

    def get_client(self, user_id: int) -> ClientProfile | None:
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT user_id, username, full_name, phone, updated_at
                FROM client_map
                WHERE user_id=?
                """,
                (user_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return ClientProfile(
            user_id=row[0],
            username=row[1],
            full_name=row[2],
            phone=row[3],
            updated_at=row[4],
        )

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

    def reset_user_state(
        self,
        user_id: int,
        chat_id: int,
        username: str | None,
    ) -> dict[str, int]:
        normalized_username = _normalize_username(username)
        with self._connect() as conn:
            deleted_pending = conn.execute(
                "DELETE FROM pending_comment WHERE user_id=?",
                (user_id,),
            ).rowcount
            deleted_client = conn.execute(
                "DELETE FROM client_map WHERE user_id=?",
                (user_id,),
            ).rowcount
            deleted_activation = conn.execute(
                "DELETE FROM user_activation WHERE user_id=?",
                (user_id,),
            ).rowcount
            deleted_reminder = conn.execute(
                "DELETE FROM reminder_context WHERE chat_id=?",
                (chat_id,),
            ).rowcount
            if normalized_username:
                deleted_user_map = conn.execute(
                    "DELETE FROM user_map WHERE username=? OR chat_id=?",
                    (normalized_username, user_id),
                ).rowcount
            else:
                deleted_user_map = conn.execute(
                    "DELETE FROM user_map WHERE chat_id=?",
                    (user_id,),
                ).rowcount
            conn.commit()
        return {
            "pending_comment": deleted_pending,
            "client_map": deleted_client,
            "user_activation": deleted_activation,
            "reminder_context": deleted_reminder,
            "user_map": deleted_user_map,
            "total": (
                deleted_pending
                + deleted_client
                + deleted_activation
                + deleted_reminder
                + deleted_user_map
            ),
        }

    def get_chat_id(self, username: str) -> int | None:
        normalized = _normalize_username(username)
        if not normalized:
            return None
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT chat_id FROM user_map WHERE username=?",
                (normalized,),
            )
            row = cur.fetchone()
        return row[0] if row else None

    def add_undelivered_event(
        self,
        created_at: datetime,
        username: str,
        kind: str,
        reason: str,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO undelivered_event (created_at, username, kind, reason)
                VALUES (?, ?, ?, ?)
                """,
                (created_at.isoformat(), username.strip(), kind.strip(), reason.strip()),
            )
            conn.commit()
        return int(cur.lastrowid)

    def set_reminder_context(
        self,
        chat_id: int,
        appointment_row: int,
        updated_at: datetime,
        status_column: str = "C",
    ) -> None:
        normalized_status_column = _normalize_status_column(status_column)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reminder_context (chat_id, appointment_row, status_column, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    appointment_row=excluded.appointment_row,
                    status_column=excluded.status_column,
                    updated_at=excluded.updated_at
                """,
                (chat_id, appointment_row, normalized_status_column, updated_at.isoformat()),
            )
            conn.commit()

    def get_reminder_context(self, chat_id: int) -> int | None:
        target = self.get_reminder_context_target(chat_id)
        return target[0] if target else None

    def get_reminder_context_target(self, chat_id: int) -> tuple[int, str] | None:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT appointment_row, status_column FROM reminder_context WHERE chat_id=?",
                (chat_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return row[0], _normalize_status_column(row[1])

    def list_unexported_undelivered(self, limit: int = 100) -> list[UndeliveredEvent]:
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT id, created_at, username, kind, reason, exported_at
                FROM undelivered_event
                WHERE exported_at IS NULL
                ORDER BY id
                LIMIT ?
                """,
                (limit,),
            )
            rows = cur.fetchall()
        return [
            UndeliveredEvent(
                id=row[0],
                created_at=row[1],
                username=row[2],
                kind=row[3],
                reason=row[4],
                exported_at=row[5],
            )
            for row in rows
        ]

    def mark_undelivered_exported(self, event_id: int, exported_at: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE undelivered_event
                SET exported_at=?
                WHERE id=?
                """,
                (exported_at.isoformat(), event_id),
            )
            conn.commit()


def _normalize_username(username: str | None) -> str:
    if not username:
        return ""
    normalized = username.strip()
    if not normalized:
        return ""
    if not normalized.startswith("@"):
        normalized = f"@{normalized}"
    return normalized.lower()


def _normalize_full_name(full_name: str | None) -> str:
    if not full_name:
        return ""
    return " ".join(full_name.split())


def _normalize_phone(phone: str | None) -> str:
    if not phone:
        return ""
    return phone.strip()


def _normalize_status_column(status_column: str | None) -> str:
    if not status_column:
        return "C"
    normalized = status_column.strip().upper()
    if not normalized or not normalized.isalpha():
        return "C"
    return normalized
