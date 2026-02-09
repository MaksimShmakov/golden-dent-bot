from app.sheets import _parse_datetime


def test_parse_datetime_with_time():
    dt = _parse_datetime("03.02.2026 18:00")
    assert dt is not None
    assert dt.strftime("%d.%m.%Y %H:%M") == "03.02.2026 18:00"


def test_parse_datetime_with_date_only():
    dt = _parse_datetime("03.02.2026")
    assert dt is not None
    assert dt.strftime("%d.%m.%Y") == "03.02.2026"