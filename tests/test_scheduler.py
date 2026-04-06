from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

from app.scheduler import (
    _build_reschedule_url,
    build_scheduler,
    schedule_birthday_messages,
    schedule_daily_messages,
    send_daily_messages,
)
from app.sheets import SheetEntry


class FakeBot:
    def __init__(self) -> None:
        self.sent_messages: list[tuple[object, str]] = []

    async def send_message(self, chat_id, text: str, reply_markup=None) -> None:  # noqa: ANN001
        self.sent_messages.append((chat_id, text))


class FakeSheets:
    def __init__(self, entries: list[SheetEntry]) -> None:
        self._entries = entries
        self.status_updates: list[tuple[str, int, str, str]] = []

    def iter_entries(self, tab_name: str):  # noqa: ANN201,ARG002
        return iter(self._entries)

    def update_appointment_status(
        self,
        tab_name: str,
        row_number: int,
        status: str,
        status_column: str = "C",
    ) -> None:
        self.status_updates.append((tab_name, row_number, status, status_column))

    def append_undelivered(self, tab_name: str, row: list[str]) -> None:  # noqa: ARG002
        return


@dataclass
class _UndeliveredEvent:
    id: int
    created_at: str
    username: str
    kind: str
    reason: str
    exported_at: str | None = None


class FakeStore:
    def __init__(self) -> None:
        self.reminder_context: tuple[int, int, str] | None = None

    def get_chat_id(self, username: str) -> int:  # noqa: ARG002
        return 10001

    def set_reminder_context(
        self,
        chat_id: int,
        appointment_row: int,
        updated_at: datetime,
        status_column: str = "C",
    ) -> None:  # noqa: ARG002
        self.reminder_context = (chat_id, appointment_row, status_column)

    def add_undelivered_event(
        self, created_at: datetime, username: str, kind: str, reason: str  # noqa: ARG002
    ) -> int:
        return 1

    def list_unexported_undelivered(self, limit: int = 100) -> list[_UndeliveredEvent]:  # noqa: ARG002
        return []

    def mark_undelivered_exported(self, event_id: int, exported_at: datetime) -> None:  # noqa: ARG002
        return


def _entry_for_day(base_day: date, day_offset: int, row_number: int) -> SheetEntry:
    dt = datetime.combine(base_day + timedelta(days=day_offset), time(10, 0))
    return SheetEntry(
        row_number=row_number,
        dt=dt,
        username="@testuser",
        status="",
        cancel_reason="",
        reminder_months=6,
        surgeon_dt=None,
    )


def test_send_daily_messages_defaults_to_tomorrow():
    zone = ZoneInfo("Asia/Novosibirsk")
    today = datetime.now(zone).date()
    sheets = FakeSheets([_entry_for_day(today, 0, 2), _entry_for_day(today, 1, 3)])
    bot = FakeBot()
    store = FakeStore()

    stats = asyncio.run(
        send_daily_messages(
            bot,
            sheets,
            "appointments",
            "undelivered",
            "Asia/Novosibirsk",
            store,
        )
    )

    assert stats["rows_total"] == 2
    assert stats["appointment_candidates"] == 1
    assert stats["sent"] == 1
    assert len(bot.sent_messages) == 1
    assert sheets.status_updates[0][0] == "appointments"
    assert sheets.status_updates[0][1] == 3
    assert sheets.status_updates[0][2]
    assert sheets.status_updates[0][3] == "C"


def test_schedule_daily_messages_sets_same_day_catchup_job_defaults():
    scheduler = build_scheduler("/tmp", "Asia/Novosibirsk")

    schedule_daily_messages(
        scheduler,
        object(),
        object(),
        "appointments",
        "undelivered",
        "Asia/Novosibirsk",
        9,
        0,
        object(),
    )

    job = scheduler.get_job("daily_messages")
    assert job is not None
    assert job.misfire_grace_time == 15 * 60 * 60
    assert job.coalesce is True
    assert job.max_instances == 1


def test_schedule_birthday_messages_sets_same_day_catchup_job_defaults():
    scheduler = build_scheduler("/tmp", "Asia/Novosibirsk")

    schedule_birthday_messages(
        scheduler,
        object(),
        object(),
        "undelivered",
        "Asia/Novosibirsk",
        9,
        0,
        object(),
        1000,
    )

    job = scheduler.get_job("birthday_messages")
    assert job is not None
    assert job.misfire_grace_time == 15 * 60 * 60
    assert job.coalesce is True
    assert job.max_instances == 1


def test_send_daily_messages_can_target_today():
    zone = ZoneInfo("Asia/Novosibirsk")
    today = datetime.now(zone).date()
    sheets = FakeSheets([_entry_for_day(today, 0, 2), _entry_for_day(today, 1, 3)])
    bot = FakeBot()
    store = FakeStore()

    stats = asyncio.run(
        send_daily_messages(
            bot,
            sheets,
            "appointments",
            "undelivered",
            "Asia/Novosibirsk",
            store,
            appointment_days_ahead=0,
        )
    )

    assert stats["rows_total"] == 2
    assert stats["appointment_candidates"] == 1
    assert stats["sent"] == 1
    assert len(bot.sent_messages) == 1
    assert sheets.status_updates[0][0] == "appointments"
    assert sheets.status_updates[0][1] == 2
    assert sheets.status_updates[0][2]
    assert sheets.status_updates[0][3] == "C"


def test_send_daily_messages_skips_periodic_overflow_months():
    zone = ZoneInfo("Asia/Novosibirsk")
    today = datetime.now(zone).date()
    dt = datetime.combine(today - timedelta(days=1), time(10, 0))
    sheets = FakeSheets(
        [
            SheetEntry(
                row_number=2,
                dt=dt,
                username="@testuser",
                status="",
                cancel_reason="",
                reminder_months=10**12,
                surgeon_dt=None,
            )
        ]
    )
    bot = FakeBot()
    store = FakeStore()

    stats = asyncio.run(
        send_daily_messages(
            bot,
            sheets,
            "appointments",
            "undelivered",
            "Asia/Novosibirsk",
            store,
        )
    )

    assert stats["rows_total"] == 1
    assert stats["periodic_candidates"] == 0
    assert stats["failed"] == 0


def test_send_daily_messages_uses_periodic_column_for_three_months():
    zone = ZoneInfo("Asia/Novosibirsk")
    today = datetime.now(zone).date()
    periodic_dt = datetime.combine(today - relativedelta(months=3), time(10, 0))
    sheets = FakeSheets(
        [
            SheetEntry(
                row_number=7,
                dt=periodic_dt,
                username="@testuser",
                status="",
                cancel_reason="",
                reminder_months=3,
                surgeon_dt=None,
                status_column="G",
                entry_kind="periodic",
            )
        ]
    )
    bot = FakeBot()
    store = FakeStore()

    stats = asyncio.run(
        send_daily_messages(
            bot,
            sheets,
            "appointments",
            "undelivered",
            "Asia/Novosibirsk",
            store,
        )
    )

    assert stats["rows_total"] == 1
    assert stats["periodic_candidates"] == 1
    assert stats["sent"] == 1
    assert sheets.status_updates[0][0] == "appointments"
    assert sheets.status_updates[0][1] == 7
    assert sheets.status_updates[0][2]
    assert sheets.status_updates[0][3] == "G"
    assert len(bot.sent_messages) == 1
    assert "3" in bot.sent_messages[0][1]
    assert store.reminder_context == (10001, 7, "G")


def test_build_reschedule_url_contains_date_and_time():
    dt = datetime(2026, 2, 27, 14, 30)
    url = _build_reschedule_url(dt)
    assert "27.02.2026%2014%3A30" in url
