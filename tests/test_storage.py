from datetime import datetime

from app.storage import SQLiteStateStore


def test_client_usernames_are_tracked_as_latest(tmp_path):
    store = SQLiteStateStore(str(tmp_path))
    now = datetime(2026, 2, 11, 10, 0, 0)

    assert store.upsert_client(1, "FirstUser", "Иван Иванов", "", now) is True
    assert store.list_client_usernames() == ["@firstuser"]

    assert store.upsert_client(1, "@FirstUser", "Иван Иванов", "", now) is False
    assert store.list_client_usernames() == ["@firstuser"]

    assert store.upsert_client(1, "SecondUser", "Иван Иванов", "", now) is True
    assert store.list_client_usernames() == ["@seconduser"]

    assert store.remove_client(1) is True
    assert store.list_client_usernames() == []
    assert store.remove_client(1) is False


def test_activation_is_marked_once(tmp_path):
    store = SQLiteStateStore(str(tmp_path))
    now = datetime(2026, 2, 11, 10, 0, 0)

    assert store.mark_activated(42, now) is True
    assert store.mark_activated(42, now) is False


def test_client_profile_contains_full_name_and_phone(tmp_path):
    store = SQLiteStateStore(str(tmp_path))
    now = datetime(2026, 2, 11, 10, 0, 0)

    assert store.upsert_client(42, "User42", "Петров Петр", "+79000000000", now) is True
    profile = store.get_client(42)
    assert profile is not None
    assert profile.username == "@user42"
    assert profile.full_name == "Петров Петр"
    assert profile.phone == "+79000000000"


def test_reminder_context_and_undelivered_events(tmp_path):
    store = SQLiteStateStore(str(tmp_path))
    now = datetime(2026, 2, 11, 10, 0, 0)

    store.set_reminder_context(chat_id=1001, appointment_row=12, updated_at=now)
    assert store.get_reminder_context(1001) == 12

    event_id = store.add_undelivered_event(
        created_at=now,
        username="@user42",
        kind="appointment",
        reason="Forbidden: bot was blocked by user",
    )
    events = store.list_unexported_undelivered()
    assert len(events) == 1
    assert events[0].id == event_id
    assert events[0].kind == "appointment"

    store.mark_undelivered_exported(event_id, now)
    assert store.list_unexported_undelivered() == []
