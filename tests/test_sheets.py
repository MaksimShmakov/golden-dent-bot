from app.sheets import (
    _iter_sheet_entries,
    _parse_admin_usernames,
    _parse_datetime,
    _parse_reminder_months,
)


def test_parse_datetime_with_time():
    dt = _parse_datetime("03.02.2026 18:00")
    assert dt is not None
    assert dt.strftime("%d.%m.%Y %H:%M") == "03.02.2026 18:00"


def test_parse_datetime_with_date_only():
    dt = _parse_datetime("03.02.2026")
    assert dt is not None
    assert dt.strftime("%d.%m.%Y") == "03.02.2026"


def test_parse_reminder_months_defaults_to_six():
    assert _parse_reminder_months("") == 6
    assert _parse_reminder_months("abc") == 6
    assert _parse_reminder_months("0") == 6


def test_parse_reminder_months_with_value():
    assert _parse_reminder_months("3") == 3
    assert _parse_reminder_months("6 мес") == 6


def test_parse_reminder_months_with_invalid_large_value_defaults_to_six():
    assert _parse_reminder_months("26022026") == 6
    assert _parse_reminder_months("999999999999") == 6


def test_iter_sheet_entries_reads_three_ranges_for_reminders():
    rows = [
        ["appt_dt", "appt_user", "appt_status", "cancel", "r3_dt", "r3_user", "r3_status"],
        [
            "27.02.2026 10:00",
            "@appointment",
            "отправлено",
            "",
            "27.11.2025 10:00",
            "@periodic3",
            "не готов",
            "",
            "",
            "27.08.2025 10:00",
            "@periodic6",
            "",
        ],
    ]

    entries = list(_iter_sheet_entries(rows))

    assert len(entries) == 3
    assert entries[0].entry_kind == "appointment"
    assert entries[0].status_column == "C"
    assert entries[0].reminder_months == 0
    assert entries[1].entry_kind == "periodic"
    assert entries[1].status_column == "G"
    assert entries[1].reminder_months == 3
    assert entries[2].entry_kind == "periodic"
    assert entries[2].status_column == "L"
    assert entries[2].reminder_months == 6


def test_iter_sheet_entries_generates_periodic_from_appointment_columns():
    rows = [
        ["appt_dt", "appt_user", "appt_status", "cancel", "months", "surgeon_dt"],
        ["27.02.2026 10:00", "@appointment", "", "", "3", ""],
    ]

    entries = list(_iter_sheet_entries(rows))

    assert len(entries) == 3
    assert entries[0].entry_kind == "appointment"
    assert entries[0].reminder_months == 0
    assert entries[1].entry_kind == "periodic"
    assert entries[1].reminder_months == 3
    assert entries[1].status_column == "G"
    assert entries[1].username == "@appointment"
    assert entries[2].entry_kind == "periodic"
    assert entries[2].reminder_months == 6
    assert entries[2].status_column == "L"
    assert entries[2].username == "@appointment"


def test_parse_admin_usernames_normalizes_and_deduplicates():
    rows = [
        ["tg_username"],
        ["AdminOne"],
        ["@AdminTwo"],
        ["adminone"],
        [""],
    ]

    assert _parse_admin_usernames(rows) == ["@adminone", "@admintwo"]
