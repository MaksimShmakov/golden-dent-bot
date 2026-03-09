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

    store.set_reminder_context(chat_id=1001, appointment_row=12, updated_at=now, status_column="L")
    assert store.get_reminder_context(1001) == 12
    assert store.get_reminder_context_target(1001) == (12, "L")

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


def test_reset_user_state_clears_user_related_data(tmp_path):
    store = SQLiteStateStore(str(tmp_path))
    now = datetime(2026, 2, 11, 10, 0, 0)

    store.upsert_user("User42", 42, now)
    store.upsert_client(42, "User42", "Петров Петр", "+79000000000", now)
    store.set_pending(
        user_id=42,
        username="@user42",
        created_at=now,
        action_type="collect_full_name",
        status_column="G",
    )
    store.set_reminder_context(chat_id=42, appointment_row=12, updated_at=now, status_column="G")
    assert store.mark_activated(42, now) is True

    stats = store.reset_user_state(user_id=42, chat_id=42, username="User42")

    assert stats["total"] == 5
    assert stats["client_map"] == 1
    assert stats["user_activation"] == 1
    assert stats["pending_comment"] == 1
    assert stats["user_map"] == 1
    assert stats["reminder_context"] == 1
    assert store.get_client(42) is None
    assert store.get_chat_id("@user42") is None
    assert store.get_reminder_context(42) is None
    assert list(store.list_pending()) == []
    assert store.mark_activated(42, now) is True


def test_special_offers_templates_can_be_seeded_and_updated(tmp_path):
    store = SQLiteStateStore(str(tmp_path))

    store.ensure_special_offers_defaults(
        header="Сезонные акции",
        offers=[
            {
                "legacy_key": "adult",
                "button_text": "Взрослый абонемент",
                "message_text": "Описание 1",
                "action_buttons": [("Записаться", "https://example.com/1")],
            },
            {
                "legacy_key": "child",
                "button_text": "Детский абонемент",
                "message_text": "Описание 2",
                "action_buttons": [("Записаться", "https://example.com/2")],
            },
        ],
    )

    assert store.get_special_offers_header() == "Сезонные акции"
    offers = store.list_offer_templates()
    assert len(offers) == 2
    assert offers[0].legacy_key == "adult"
    assert offers[1].button_text == "Детский абонемент"
    assert store.get_offer_template_by_legacy_key("adult") is not None

    new_offer_id = store.add_offer_template(
        button_text="Имплантация",
        message_text="Описание 3",
        action_buttons=[("Подробнее", "https://example.com/3")],
    )
    added = store.get_offer_template(new_offer_id)
    assert added is not None
    assert added.sort_order == 3

    assert store.update_offer_template(
        new_offer_id,
        button_text="Имплантация + коронка",
        message_text="Новое описание 3",
        action_buttons=[("Записаться", "https://example.com/new")],
    )
    updated = store.get_offer_template(new_offer_id)
    assert updated is not None
    assert updated.button_text == "Имплантация + коронка"
    assert updated.action_buttons == [("Записаться", "https://example.com/new")]

    assert store.delete_offer_template(offers[0].id) is True
    reordered = store.list_offer_templates()
    assert [offer.sort_order for offer in reordered] == [1, 2]
