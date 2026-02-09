from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

import gspread


@dataclass
class SheetEntry:
    dt: datetime
    username: str


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

    def iter_entries(self, tab_name: str) -> Iterable[SheetEntry]:
        ws = self._sheet.worksheet(tab_name)
        rows = ws.get_all_values()
        for row in rows[1:]:
            if not row or not row[0].strip():
                continue
            dt = _parse_datetime(row[0].strip())
            if not dt:
                continue
            username = row[1].strip() if len(row) > 1 else ""
            if not username:
                continue
            yield SheetEntry(dt=dt, username=username)


def _parse_datetime(value: str) -> datetime | None:
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None
