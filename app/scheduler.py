from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dateutil.relativedelta import relativedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from app.messages import send_birthday_message, send_main_message
from app.sheets import SheetsClient
from app.storage import ClientProfile, SQLiteStateStore

logger = logging.getLogger("golden-dent")
_ADMIN_USERNAME = "GoldenDentNSK"
_FAILED_EXAMPLES_LIMIT = 5


def build_scheduler(data_dir: str, tz: str) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=ZoneInfo(tz))
    return scheduler


def schedule_daily_messages(
    scheduler: AsyncIOScheduler,
    bot,
    sheets: SheetsClient,
    appointments_tab: str,
    undelivered_tab: str,
    tz: str,
    hour: int,
    minute: int,
    store: SQLiteStateStore,
) -> None:
    trigger = CronTrigger(hour=hour, minute=minute, timezone=ZoneInfo(tz))
    scheduler.add_job(
        send_daily_messages,
        trigger=trigger,
        id="daily_messages",
        replace_existing=True,
        args=[bot, sheets, appointments_tab, undelivered_tab, tz, store],
    )


def schedule_birthday_messages(
    scheduler: AsyncIOScheduler,
    bot,
    sheets: SheetsClient,
    undelivered_tab: str,
    tz: str,
    hour: int,
    minute: int,
    store: SQLiteStateStore,
    bonus_amount: int,
) -> None:
    trigger = CronTrigger(hour=hour, minute=minute, timezone=ZoneInfo(tz))
    scheduler.add_job(
        send_birthday_messages,
        trigger=trigger,
        id="birthday_messages",
        replace_existing=True,
        args=[bot, sheets, undelivered_tab, tz, store, bonus_amount],
    )


def flush_undelivered_events(
    sheets: SheetsClient,
    undelivered_tab: str,
    tz: str,
    store: SQLiteStateStore,
) -> None:
    _flush_undelivered(sheets, undelivered_tab, ZoneInfo(tz), store)


async def send_daily_messages(
    bot,
    sheets: SheetsClient,
    tab_name: str,
    undelivered_tab: str,
    tz: str,
    store: SQLiteStateStore,
    appointment_days_ahead: int = 1,
) -> dict[str, object]:
    zone = ZoneInfo(tz)
    today = datetime.now(zone).date()
    target_date = today + timedelta(days=appointment_days_ahead)
    _flush_undelivered(sheets, undelivered_tab, zone, store)
    stats: dict[str, object] = {
        "rows_total": 0,
        "appointment_candidates": 0,
        "surgeon_candidates": 0,
        "periodic_candidates": 0,
        "sent": 0,
        "failed": 0,
        "failed_examples": [],
    }

    for entry in sheets.iter_entries(tab_name):
        stats["rows_total"] = int(stats["rows_total"]) + 1
        entry_date = entry.dt.date()

        if entry.entry_kind == "appointment" and entry_date == target_date:
            stats["appointment_candidates"] = int(stats["appointment_candidates"]) + 1
            sent, failure_reason = await _send_appointment_message(
                bot=bot,
                sheets=sheets,
                appointments_tab=tab_name,
                undelivered_tab=undelivered_tab,
                username=entry.username,
                dt=entry.dt,
                row_number=entry.row_number,
                zone=zone,
                store=store,
                kind="appointment",
                text_prefix="Здравствуйте! Вы записаны на завтра",
                status_column=entry.status_column,
            )
            _apply_delivery_stats(stats, entry.username, sent, failure_reason)

        if (
            entry.entry_kind == "appointment"
            and entry.surgeon_dt
            and entry.surgeon_dt.date() == target_date
            and entry.surgeon_dt != entry.dt
        ):
            stats["surgeon_candidates"] = int(stats["surgeon_candidates"]) + 1
            sent, failure_reason = await _send_appointment_message(
                bot=bot,
                sheets=sheets,
                appointments_tab=tab_name,
                undelivered_tab=undelivered_tab,
                username=entry.username,
                dt=entry.surgeon_dt,
                row_number=entry.row_number,
                zone=zone,
                store=store,
                kind="surgeon_appointment",
                text_prefix=(
                    "Здравствуйте! Вы записаны "
                    "на плановый визит хирурга завтра"
                ),
                status_column=entry.status_column,
            )
            _apply_delivery_stats(stats, entry.username, sent, failure_reason)

        try:
            periodic_due = (
                entry.reminder_months > 0
                and entry_date + relativedelta(months=+entry.reminder_months) == today
            )
        except OverflowError:
            logger.warning(
                "Skip periodic reminder for row %s: invalid reminder_months=%s",
                entry.row_number,
                entry.reminder_months,
            )
            periodic_due = False

        if periodic_due:
            stats["periodic_candidates"] = int(stats["periodic_candidates"]) + 1
            sent, failure_reason = await _send_periodic_message(
                bot=bot,
                sheets=sheets,
                appointments_tab=tab_name,
                undelivered_tab=undelivered_tab,
                username=entry.username,
                row_number=entry.row_number,
                reminder_months=entry.reminder_months,
                zone=zone,
                store=store,
                status_column=entry.status_column,
            )
            _apply_delivery_stats(stats, entry.username, sent, failure_reason)

    return stats


async def send_birthday_messages(
    bot,
    sheets: SheetsClient,
    undelivered_tab: str,
    tz: str,
    store: SQLiteStateStore,
    bonus_amount: int,
    target_date: date | None = None,
) -> dict[str, object]:
    zone = ZoneInfo(tz)
    today = target_date or datetime.now(zone).date()
    sent_on = today.isoformat()
    _flush_undelivered(sheets, undelivered_tab, zone, store)

    stats: dict[str, object] = {
        "candidates": 0,
        "sent": 0,
        "failed": 0,
        "already_sent": 0,
        "failed_examples": [],
    }

    for client in store.list_clients():
        birth_date = _parse_birth_date(client.birth_date)
        if not birth_date or not client.consent_given_at:
            continue
        if (birth_date.month, birth_date.day) != (today.month, today.day):
            continue

        stats["candidates"] = int(stats["candidates"]) + 1
        if store.has_birthday_message_for_day(client.user_id, sent_on):
            stats["already_sent"] = int(stats["already_sent"]) + 1
            continue

        target, failure_reason = _resolve_private_target(store, client.username, client.user_id)
        target_label = client.username or f"id:{client.user_id}"
        if target is None:
            stats["failed"] = int(stats["failed"]) + 1
            _push_failed_example(stats, target_label, failure_reason or "unknown target")
            _log_undelivered(
                sheets=sheets,
                undelivered_tab=undelivered_tab,
                zone=zone,
                store=store,
                username=target_label,
                kind="birthday",
                reason=failure_reason or "missing chat id",
            )
            continue

        try:
            await send_birthday_message(bot, target, bonus_amount=bonus_amount)
            store.mark_birthday_message_sent(client.user_id, sent_on, bonus_amount, datetime.now(zone))
            stats["sent"] = int(stats["sent"]) + 1
        except TelegramError as exc:
            logger.warning("Failed to send birthday message to %s: %s", target_label, exc)
            stats["failed"] = int(stats["failed"]) + 1
            _push_failed_example(stats, target_label, str(exc))
            _log_undelivered(
                sheets=sheets,
                undelivered_tab=undelivered_tab,
                zone=zone,
                store=store,
                username=target_label,
                kind="birthday",
                reason=str(exc),
            )

    return stats


async def _send_appointment_message(
    bot,
    sheets: SheetsClient,
    appointments_tab: str,
    undelivered_tab: str,
    username: str,
    dt: datetime,
    row_number: int,
    zone,
    store: SQLiteStateStore,
    kind: str,
    text_prefix: str,
    status_column: str,
) -> tuple[bool, str | None]:
    local_dt = dt.replace(tzinfo=zone) if dt.tzinfo is None else dt.astimezone(zone)
    date_str = local_dt.strftime("%d.%m.%Y")
    time_str = local_dt.strftime("%H:%M")
    text = (
        f"{text_prefix} "
        f"{date_str} г в клинику «Голден Дент» на прием в {time_str} 🕥"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Подтвердить запись",
                    callback_data=f"confirm_appt:{row_number}",
                )
            ],
            [
                InlineKeyboardButton(
                    "Отменить запись",
                    callback_data=f"cancel_appt:{row_number}",
                )
            ],
            [InlineKeyboardButton("Перенести запись", url=_build_reschedule_url(local_dt))],
        ]
    )
    target, failure_reason = _resolve_private_target(store, username)
    if target is None:
        _log_undelivered(
            sheets=sheets,
            undelivered_tab=undelivered_tab,
            zone=zone,
            store=store,
            username=username,
            kind=kind,
            reason=failure_reason or "missing chat id",
        )
        return False, failure_reason

    try:
        await bot.send_message(chat_id=target, text=text, reply_markup=keyboard)
        sheets.update_appointment_status(
            appointments_tab,
            row_number,
            "отправлено",
            status_column,
        )
        return True, None
    except TelegramError as exc:
        logger.warning("Failed to send appointment to %s: %s", username, exc)
        _log_undelivered(
            sheets=sheets,
            undelivered_tab=undelivered_tab,
            zone=zone,
            store=store,
            username=username,
            kind=kind,
            reason=str(exc),
        )
        return False, str(exc)


async def _send_periodic_message(
    bot,
    sheets: SheetsClient,
    appointments_tab: str,
    undelivered_tab: str,
    username: str,
    row_number: int,
    reminder_months: int,
    zone,
    store: SQLiteStateStore,
    status_column: str,
) -> tuple[bool, str | None]:
    target, failure_reason = _resolve_private_target(store, username)
    if target is None:
        _log_undelivered(
            sheets=sheets,
            undelivered_tab=undelivered_tab,
            zone=zone,
            store=store,
            username=username,
            kind=f"{reminder_months}m",
            reason=failure_reason or "missing chat id",
        )
        return False, failure_reason

    try:
        await send_main_message(bot, target, reminder_months=reminder_months)
        sheets.update_appointment_status(
            appointments_tab,
            row_number,
            "отправлено",
            status_column,
        )
        store.set_reminder_context(
            int(target),
            row_number,
            datetime.now(zone),
            status_column=status_column,
        )
        return True, None
    except TelegramError as exc:
        logger.warning("Failed to send periodic reminder to %s: %s", username, exc)
        _log_undelivered(
            sheets=sheets,
            undelivered_tab=undelivered_tab,
            zone=zone,
            store=store,
            username=username,
            kind=f"{reminder_months}m",
            reason=str(exc),
        )
        return False, str(exc)


def _resolve_private_target(
    store: SQLiteStateStore,
    username: str,
    fallback_chat_id: int | None = None,
) -> tuple[int | None, str | None]:
    chat_id = store.get_chat_id(username)
    if chat_id:
        return chat_id, None

    cleaned = username.strip()
    if cleaned.isdigit():
        return int(cleaned), None
    if cleaned.startswith("id:") and cleaned[3:].isdigit():
        return int(cleaned[3:]), None
    if fallback_chat_id:
        return fallback_chat_id, None

    return None, "user has not started the bot or username does not match the stored chat"


def _apply_delivery_stats(
    stats: dict[str, object],
    username: str,
    sent: bool,
    failure_reason: str | None,
) -> None:
    if sent:
        stats["sent"] = int(stats["sent"]) + 1
        return
    stats["failed"] = int(stats["failed"]) + 1
    _push_failed_example(stats, username, failure_reason or "unknown error")


def _push_failed_example(stats: dict[str, object], username: str, reason: str) -> None:
    failed_examples = stats.setdefault("failed_examples", [])
    if not isinstance(failed_examples, list):
        return
    if len(failed_examples) >= _FAILED_EXAMPLES_LIMIT:
        return
    failed_examples.append(f"{username}: {reason}")


def _parse_birth_date(value: str) -> date | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _build_reschedule_url(dt: datetime) -> str:
    date_time_str = dt.strftime("%d.%m.%Y %H:%M")
    text = f"Здравствуйте! Хочу перенести мою запись {date_time_str}"
    return f"https://t.me/{_ADMIN_USERNAME}?text={quote(text)}"


def _log_undelivered(
    sheets: SheetsClient,
    undelivered_tab: str,
    zone,
    store: SQLiteStateStore,
    username: str,
    kind: str,
    reason: str,
) -> None:
    store.add_undelivered_event(datetime.now(zone), username, kind, reason)
    _flush_undelivered(sheets, undelivered_tab, zone, store)


def _flush_undelivered(
    sheets: SheetsClient,
    undelivered_tab: str,
    zone,
    store: SQLiteStateStore,
) -> None:
    events = store.list_unexported_undelivered(limit=500)
    if not events:
        return

    exported_at = datetime.now(zone)
    for event in events:
        try:
            created = datetime.fromisoformat(event.created_at)
            created_local = (
                created.replace(tzinfo=zone) if created.tzinfo is None else created.astimezone(zone)
            )
            sheets.append_undelivered(
                undelivered_tab,
                [
                    created_local.strftime("%d.%m.%Y %H:%M"),
                    event.username,
                    event.kind,
                    event.reason,
                ],
            )
            store.mark_undelivered_exported(event.id, exported_at)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to flush undelivered event %s: %s", event.id, exc)
            break
