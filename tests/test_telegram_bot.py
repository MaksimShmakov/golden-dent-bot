from app.telegram_bot import _parse_test_daily_days_ahead


def test_parse_test_daily_days_ahead_defaults_to_tomorrow():
    assert _parse_test_daily_days_ahead([]) == 1
    assert _parse_test_daily_days_ahead(["unknown"]) == 1


def test_parse_test_daily_days_ahead_today_aliases():
    assert _parse_test_daily_days_ahead(["today"]) == 0
    assert _parse_test_daily_days_ahead(["сегодня"]) == 0
    assert _parse_test_daily_days_ahead(["0"]) == 0


def test_parse_test_daily_days_ahead_numeric_and_tomorrow_aliases():
    assert _parse_test_daily_days_ahead(["tomorrow"]) == 1
    assert _parse_test_daily_days_ahead(["завтра"]) == 1
    assert _parse_test_daily_days_ahead(["+2"]) == 2
