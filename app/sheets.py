from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

import gspread

from app.storage import ClientProfile


@dataclass
class SheetEntry:
    row_number: int
    dt: datetime
    username: str
    status: str
    cancel_reason: str
    reminder_months: int
    surgeon_dt: datetime | None
    status_column: str = "C"
    entry_kind: str = "appointment"


class SheetsClient:
    def __init__(self, sheet_id: str, service_account_json: str) -> None:
        self._gc = gspread.service_account(filename=service_account_json)
        self._sheet = self._gc.open_by_key(sheet_id)

    def append_comment(self, tab_name: str, row: list[str]) -> None:
        ws = self._sheet.worksheet(tab_name)
        ws.append_row(row, value_input_option="USER_ENTERED")

    def append_undelivered(self, tab_name: str, row: list[str]) -> None:
        ws = self._sheet.worksheet(tab_name)
        ws.append_row(row, value_input_option="USER_ENTERED")

    def sync_client_usernames(self, tab_name: str, usernames: list[str]) -> None:
        unique_usernames = sorted(
            {username.strip().lower() for username in usernames if username.strip()}
        )
        clients = [
            ClientProfile(
                user_id=-index,
                username=username,
                full_name="",
                phone="",
                updated_at="",
            )
            for index, username in enumerate(unique_usernames, start=1)
        ]
        self.sync_clients(tab_name, clients)

    def sync_clients(self, tab_name: str, clients: list[ClientProfile]) -> None:
        ws = self._sheet.worksheet(tab_name)
        existing_rows = ws.get_all_values()
        default_header = ["tg_username", "fio", "phone", "tg_user_id"]

        if existing_rows:
            existing_header = (existing_rows[0] + ["", "", "", ""])[:4]
            header = [
                existing_header[0].strip() or default_header[0],
                existing_header[1].strip() or default_header[1],
                existing_header[2].strip() or default_header[2],
                existing_header[3].strip() or default_header[3],
            ]
        else:
            header = default_header

        unique_clients: dict[int, ClientProfile] = {}
        for client in clients:
            unique_clients[client.user_id] = client
        sorted_clients = sorted(
            unique_clients.values(),
            key=lambda item: (item.username == "", item.username, item.user_id),
        )

        target_rows = [header]
        for client in sorted_clients:
            target_rows.append(
                [
                    client.username,
                    client.full_name,
                    client.phone,
                    str(client.user_id) if client.user_id else "",
                ]
            )

        existing_projection = [
            (row + ["", "", "", ""])[:4] for row in existing_rows
        ]
        if existing_projection == target_rows:
            return

        ws.update(
            f"A1:D{len(target_rows)}",
            target_rows,
            value_input_option="USER_ENTERED",
        )
        if len(existing_projection) > len(target_rows):
            ws.batch_clear([f"A{len(target_rows) + 1}:D{len(existing_projection)}"])

    def update_appointment_status(
        self,
        tab_name: str,
        row_number: int,
        status: str,
        status_column: str = "C",
    ) -> None:
        if row_number < 2:
            return
        column = _normalize_status_column(status_column)
        ws = self._sheet.worksheet(tab_name)
        ws.update(
            f"{column}{row_number}:{column}{row_number}",
            [[status]],
            value_input_option="USER_ENTERED",
        )

    def update_appointment_cancel_reason(
        self, tab_name: str, row_number: int, reason: str
    ) -> None:
        if row_number < 2:
            return
        ws = self._sheet.worksheet(tab_name)
        ws.update(
            f"D{row_number}:D{row_number}",
            [[reason]],
            value_input_option="USER_ENTERED",
        )

    def iter_entries(self, tab_name: str) -> Iterable[SheetEntry]:
        ws = self._sheet.worksheet(tab_name)
        rows = ws.get_all_values()
        yield from _iter_sheet_entries(rows)


def _iter_sheet_entries(rows: list[list[str]]) -> Iterable[SheetEntry]:
    for row_number, row in enumerate(rows[1:], start=2):
        appointment_entry = _build_appointment_entry(row_number, row)
        if appointment_entry:
            yield appointment_entry

        periodic_3m = _build_periodic_entry(
            row_number=row_number,
            row=row,
            date_index=4,
            username_index=5,
            status_index=6,
            reminder_months=3,
            status_column="G",
        )
        if not periodic_3m and appointment_entry:
            periodic_3m = _build_periodic_entry_from_base(
                row_number=row_number,
                dt=appointment_entry.dt,
                username=appointment_entry.username,
                status=_cell_value(row, 6),
                reminder_months=3,
                status_column="G",
            )
        if periodic_3m:
            yield periodic_3m

        periodic_6m = _build_periodic_entry(
            row_number=row_number,
            row=row,
            date_index=9,
            username_index=10,
            status_index=11,
            reminder_months=6,
            status_column="L",
        )
        if not periodic_6m and appointment_entry:
            periodic_6m = _build_periodic_entry_from_base(
                row_number=row_number,
                dt=appointment_entry.dt,
                username=appointment_entry.username,
                status=_cell_value(row, 11),
                reminder_months=6,
                status_column="L",
            )
        if periodic_6m:
            yield periodic_6m


def _build_appointment_entry(row_number: int, row: list[str]) -> SheetEntry | None:
    date_raw = _cell_value(row, 0)
    dt = _parse_datetime(date_raw) if date_raw else None
    if not dt:
        return None

    username = _cell_value(row, 1)
    if not username:
        return None

    return SheetEntry(
        row_number=row_number,
        dt=dt,
        username=username,
        status=_cell_value(row, 2),
        cancel_reason=_cell_value(row, 3),
        reminder_months=0,
        surgeon_dt=None,
        status_column="C",
        entry_kind="appointment",
    )


def _build_periodic_entry(
    row_number: int,
    row: list[str],
    date_index: int,
    username_index: int,
    status_index: int,
    reminder_months: int,
    status_column: str,
) -> SheetEntry | None:
    date_raw = _cell_value(row, date_index)
    dt = _parse_datetime(date_raw) if date_raw else None
    if not dt:
        return None

    username = _cell_value(row, username_index)
    if not username:
        return None

    return SheetEntry(
        row_number=row_number,
        dt=dt,
        username=username,
        status=_cell_value(row, status_index),
        cancel_reason="",
        reminder_months=reminder_months,
        surgeon_dt=None,
        status_column=status_column,
        entry_kind="periodic",
    )


def _build_periodic_entry_from_base(
    row_number: int,
    dt: datetime,
    username: str,
    status: str,
    reminder_months: int,
    status_column: str,
) -> SheetEntry:
    return SheetEntry(
        row_number=row_number,
        dt=dt,
        username=username,
        status=status,
        cancel_reason="",
        reminder_months=reminder_months,
        surgeon_dt=None,
        status_column=status_column,
        entry_kind="periodic",
    )


def _cell_value(row: list[str], index: int) -> str:
    if len(row) <= index:
        return ""
    return row[index].strip()


def _normalize_status_column(status_column: str | None) -> str:
    if not status_column:
        return "C"
    normalized = status_column.strip().upper()
    if not normalized or not normalized.isalpha():
        return "C"
    return normalized


def _parse_datetime(value: str) -> datetime | None:
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _parse_reminder_months(value: str) -> int:
    cleaned = value.strip()
    if not cleaned:
        return 6
    digits = "".join(ch for ch in cleaned if ch.isdigit())
    if not digits:
        return 6
    months = int(digits)
    # Guard against wrong columns/dirty values like dates or phone numbers.
    if months <= 0 or months > 120:
        return 6
    return months
