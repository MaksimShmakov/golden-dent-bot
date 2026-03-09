from __future__ import annotations

import json
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


@dataclass
class OfferTemplate:
    id: int
    legacy_key: str
    sort_order: int
    button_text: str
    message_text: str
    action_buttons: list[tuple[str, str]]


class SQLiteStateStore:
    _SPECIAL_OFFERS_HEADER_KEY = "special_offers_header"

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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS offer_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS offer_template (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    legacy_key TEXT NOT NULL DEFAULT '',
                    sort_order INTEGER NOT NULL,
                    button_text TEXT NOT NULL,
                    message_text TEXT NOT NULL,
                    action_buttons_json TEXT NOT NULL DEFAULT '[]'
                )
                """
            )
            self._migrate_pending_comment_schema(conn)
            self._migrate_client_map_schema(conn)
            self._migrate_reminder_context_schema(conn)
            self._migrate_offer_template_schema(conn)
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

    def _migrate_offer_template_schema(self, conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(offer_template)").fetchall()}
        if not columns:
            return
        if "legacy_key" not in columns:
            conn.execute("ALTER TABLE offer_template ADD COLUMN legacy_key TEXT NOT NULL DEFAULT ''")
        if "sort_order" not in columns:
            conn.execute("ALTER TABLE offer_template ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
        if "action_buttons_json" not in columns:
            conn.execute(
                "ALTER TABLE offer_template ADD COLUMN action_buttons_json TEXT NOT NULL DEFAULT '[]'"
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

    def ensure_special_offers_defaults(
        self,
        header: str,
        offers: list[dict[str, object]],
    ) -> None:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT value FROM offer_settings WHERE key=?",
                (self._SPECIAL_OFFERS_HEADER_KEY,),
            )
            header_row = cur.fetchone()
            if not header_row:
                conn.execute(
                    "INSERT INTO offer_settings (key, value) VALUES (?, ?)",
                    (self._SPECIAL_OFFERS_HEADER_KEY, _normalize_offer_text(header)),
                )

            cur = conn.execute("SELECT COUNT(1) FROM offer_template")
            offer_count = int(cur.fetchone()[0])
            if offer_count == 0:
                for index, offer in enumerate(offers, start=1):
                    button_text = _normalize_offer_text(offer.get("button_text"))
                    message_text = _normalize_offer_text(offer.get("message_text"))
                    legacy_key = _normalize_legacy_key(offer.get("legacy_key"))
                    action_buttons = _normalize_offer_buttons(
                        offer.get("action_buttons", []),
                    )
                    if not button_text or not message_text:
                        continue
                    conn.execute(
                        """
                        INSERT INTO offer_template (
                            legacy_key,
                            sort_order,
                            button_text,
                            message_text,
                            action_buttons_json
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            legacy_key,
                            index,
                            button_text,
                            message_text,
                            _serialize_offer_buttons(action_buttons),
                        ),
                    )
            conn.commit()

    def get_special_offers_header(self, fallback: str = "") -> str:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT value FROM offer_settings WHERE key=?",
                (self._SPECIAL_OFFERS_HEADER_KEY,),
            )
            row = cur.fetchone()
        if not row:
            return _normalize_offer_text(fallback)
        return _normalize_offer_text(row[0]) or _normalize_offer_text(fallback)

    def set_special_offers_header(self, value: str) -> None:
        normalized = _normalize_offer_text(value)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO offer_settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value
                """,
                (self._SPECIAL_OFFERS_HEADER_KEY, normalized),
            )
            conn.commit()

    def list_offer_templates(self) -> list[OfferTemplate]:
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT id, legacy_key, sort_order, button_text, message_text, action_buttons_json
                FROM offer_template
                ORDER BY sort_order, id
                """
            )
            rows = cur.fetchall()
        return [_offer_row_to_dataclass(row) for row in rows]

    def get_offer_template(self, offer_id: int) -> OfferTemplate | None:
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT id, legacy_key, sort_order, button_text, message_text, action_buttons_json
                FROM offer_template
                WHERE id=?
                """,
                (offer_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return _offer_row_to_dataclass(row)

    def get_offer_template_by_legacy_key(self, legacy_key: str) -> OfferTemplate | None:
        normalized_legacy_key = _normalize_legacy_key(legacy_key)
        if not normalized_legacy_key:
            return None
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT id, legacy_key, sort_order, button_text, message_text, action_buttons_json
                FROM offer_template
                WHERE legacy_key=?
                LIMIT 1
                """,
                (normalized_legacy_key,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return _offer_row_to_dataclass(row)

    def add_offer_template(
        self,
        button_text: str,
        message_text: str,
        action_buttons: list[tuple[str, str]],
        legacy_key: str = "",
    ) -> int:
        normalized_button_text = _normalize_offer_text(button_text)
        normalized_message_text = _normalize_offer_text(message_text)
        normalized_legacy_key = _normalize_legacy_key(legacy_key)
        normalized_buttons = _normalize_offer_buttons(action_buttons)
        if not normalized_button_text:
            raise ValueError("button_text must not be empty")
        if not normalized_message_text:
            raise ValueError("message_text must not be empty")
        with self._connect() as conn:
            cur = conn.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM offer_template")
            next_sort_order = int(cur.fetchone()[0])
            cur = conn.execute(
                """
                INSERT INTO offer_template (
                    legacy_key,
                    sort_order,
                    button_text,
                    message_text,
                    action_buttons_json
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    normalized_legacy_key,
                    next_sort_order,
                    normalized_button_text,
                    normalized_message_text,
                    _serialize_offer_buttons(normalized_buttons),
                ),
            )
            conn.commit()
        return int(cur.lastrowid)

    def update_offer_template(
        self,
        offer_id: int,
        *,
        button_text: str | None = None,
        message_text: str | None = None,
        action_buttons: list[tuple[str, str]] | None = None,
    ) -> bool:
        current = self.get_offer_template(offer_id)
        if not current:
            return False

        next_button_text = current.button_text
        if button_text is not None:
            next_button_text = _normalize_offer_text(button_text)
        next_message_text = current.message_text
        if message_text is not None:
            next_message_text = _normalize_offer_text(message_text)
        next_action_buttons = current.action_buttons
        if action_buttons is not None:
            next_action_buttons = _normalize_offer_buttons(action_buttons)

        if not next_button_text:
            raise ValueError("button_text must not be empty")
        if not next_message_text:
            raise ValueError("message_text must not be empty")

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE offer_template
                SET button_text=?, message_text=?, action_buttons_json=?
                WHERE id=?
                """,
                (
                    next_button_text,
                    next_message_text,
                    _serialize_offer_buttons(next_action_buttons),
                    offer_id,
                ),
            )
            conn.commit()
        return True

    def delete_offer_template(self, offer_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM offer_template WHERE id=?", (offer_id,))
            deleted = cur.rowcount > 0
            if deleted:
                self._reorder_offer_templates(conn)
            conn.commit()
        return deleted

    def _reorder_offer_templates(self, conn: sqlite3.Connection) -> None:
        cur = conn.execute("SELECT id FROM offer_template ORDER BY sort_order, id")
        for index, row in enumerate(cur.fetchall(), start=1):
            conn.execute(
                "UPDATE offer_template SET sort_order=? WHERE id=?",
                (index, row[0]),
            )

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


def _normalize_offer_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_legacy_key(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _normalize_offer_buttons(value: object) -> list[tuple[str, str]]:
    if not isinstance(value, list):
        return []

    normalized: list[tuple[str, str]] = []
    for raw_button in value:
        if not isinstance(raw_button, (list, tuple)) or len(raw_button) != 2:
            continue
        text = _normalize_offer_text(raw_button[0])
        url = _normalize_offer_text(raw_button[1])
        if not text or not url:
            continue
        normalized.append((text, url))
    return normalized[:10]


def _serialize_offer_buttons(buttons: list[tuple[str, str]]) -> str:
    payload = [{"text": text, "url": url} for text, url in buttons]
    return json.dumps(payload, ensure_ascii=False)


def _deserialize_offer_buttons(payload: str) -> list[tuple[str, str]]:
    if not payload:
        return []
    try:
        raw_buttons = json.loads(payload)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw_buttons, list):
        return []
    normalized: list[tuple[str, str]] = []
    for raw_button in raw_buttons:
        if not isinstance(raw_button, dict):
            continue
        text = _normalize_offer_text(raw_button.get("text"))
        url = _normalize_offer_text(raw_button.get("url"))
        if not text or not url:
            continue
        normalized.append((text, url))
    return normalized[:10]


def _offer_row_to_dataclass(row: tuple) -> OfferTemplate:
    return OfferTemplate(
        id=int(row[0]),
        legacy_key=_normalize_legacy_key(row[1]),
        sort_order=int(row[2]),
        button_text=_normalize_offer_text(row[3]),
        message_text=_normalize_offer_text(row[4]),
        action_buttons=_deserialize_offer_buttons(str(row[5])),
    )
