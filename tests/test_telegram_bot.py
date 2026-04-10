from app.storage import SQLiteStateStore
from app.telegram_bot import (
    _parse_broadcast_buttons,
    _parse_broadcast_usernames,
    _parse_full_name_segments,
    _parse_test_daily_days_ahead,
    _resolve_broadcast_target,
    _split_telegram_text,
)


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


def test_parse_broadcast_usernames_normalizes_and_deduplicates():
    usernames = _parse_broadcast_usernames("@One, two\nTHREE; id:12345 12345 @one")
    assert usernames == ["@one", "@two", "@three", "id:12345", "12345"]


def test_parse_broadcast_buttons_validates_format_and_url():
    buttons, error = _parse_broadcast_buttons(
        "Открыть сайт | https://example.com\nНаписать | https://t.me/test"
    )
    assert error is None
    assert buttons == [
        ("Открыть сайт", "https://example.com"),
        ("Написать", "https://t.me/test"),
    ]

    buttons, error = _parse_broadcast_buttons("Без ссылки | not-a-url")
    assert buttons == []
    assert error is not None


def test_resolve_broadcast_target_requires_known_private_chat(tmp_path):
    store = SQLiteStateStore(str(tmp_path))

    target, reason = _resolve_broadcast_target(store, "@missinguser")

    assert target is None
    assert reason is not None


def test_split_telegram_text_preserves_content():
    text = ("A" * 3000) + "\n\n" + ("B" * 3000)

    chunks = _split_telegram_text(text, limit=4096)

    assert len(chunks) == 2
    assert chunks[0] == "A" * 3000
    assert chunks[1] == "B" * 3000
