from app.sheets import _parse_datetime, _parse_reminder_months


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
