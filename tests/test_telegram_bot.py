from app.telegram_bot import _parse_full_name_segments, _parse_test_daily_days_ahead


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


def test_parse_full_name_segments_accepts_segmented_name():
    assert _parse_full_name_segments("Иванов Иван Иванович") == "Иванов Иван Иванович"
    assert _parse_full_name_segments("Иванов   Иван") == "Иванов Иван"


def test_parse_full_name_segments_rejects_non_segmented_or_too_long_name():
    assert _parse_full_name_segments("") == ""
    assert _parse_full_name_segments("Иван") == ""
    assert _parse_full_name_segments("Иванов Иван Иванович Петров Сидоров") == ""
