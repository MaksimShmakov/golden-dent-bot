from datetime import datetime

from app.storage import SQLiteStateStore


def test_client_usernames_are_tracked_as_latest(tmp_path):
    store = SQLiteStateStore(str(tmp_path))
    now = datetime(2026, 2, 11, 10, 0, 0)

    assert store.upsert_client(1, "FirstUser", now) is True
    assert store.list_client_usernames() == ["@firstuser"]

    assert store.upsert_client(1, "@FirstUser", now) is False
    assert store.list_client_usernames() == ["@firstuser"]

    assert store.upsert_client(1, "SecondUser", now) is True
    assert store.list_client_usernames() == ["@seconduser"]

    assert store.remove_client(1) is True
    assert store.list_client_usernames() == []
    assert store.remove_client(1) is False


def test_activation_is_marked_once(tmp_path):
    store = SQLiteStateStore(str(tmp_path))
    now = datetime(2026, 2, 11, 10, 0, 0)

    assert store.mark_activated(42, now) is True
    assert store.mark_activated(42, now) is False
