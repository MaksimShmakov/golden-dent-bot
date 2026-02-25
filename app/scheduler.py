from __future__ import annotations

import logging
from datetime import datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dateutil.relativedelta import relativedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from app.messages import send_main_message
from app.sheets import SheetsClient
from app.storage import SQLiteStateStore

logger = logging.getLogger("golden-dent")
_ADMIN_USERNAME = "GoldenDentNSK"


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
) -> dict[str, int]:
    zone = ZoneInfo(tz)
    today = datetime.now(zone).date()
    target_date = today + timedelta(days=appointment_days_ahead)
    _flush_undelivered(sheets, undelivered_tab, zone, store)
    stats = {
        "rows_total": 0,
        "appointment_candidates": 0,
        "surgeon_candidates": 0,
        "periodic_candidates": 0,
        "sent": 0,
        "failed": 0,
    }

    for entry in sheets.iter_entries(tab_name):
        stats["rows_total"] += 1
        entry_date = entry.dt.date()

        if entry_date == target_date:
            stats["appointment_candidates"] += 1
            sent = await _send_appointment_message(
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
            )
            stats["sent"] += int(sent)
            stats["failed"] += int(not sent)

        if (
            entry.surgeon_dt
            and entry.surgeon_dt.date() == target_date
            and entry.surgeon_dt != entry.dt
        ):
            stats["surgeon_candidates"] += 1
            sent = await _send_appointment_message(
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
                text_prefix="Здравствуйте! Вы записаны на плановый визит хирурга завтра",
            )
            stats["sent"] += int(sent)
            stats["failed"] += int(not sent)

        if entry_date + relativedelta(months=+entry.reminder_months) == today:
            stats["periodic_candidates"] += 1
            sent = await _send_periodic_message(
                bot=bot,
                sheets=sheets,
                appointments_tab=tab_name,
                undelivered_tab=undelivered_tab,
                username=entry.username,
                row_number=entry.row_number,
                reminder_months=entry.reminder_months,
                zone=zone,
                store=store,
            )
            stats["sent"] += int(sent)
            stats["failed"] += int(not sent)

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
) -> bool:
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
    chat_id = store.get_chat_id(username)
    fallback = username if username.startswith("@") or username.isdigit() else f"@{username}"
    try:
        await bot.send_message(chat_id=chat_id or fallback, text=text, reply_markup=keyboard)
        sheets.update_appointment_status(appointments_tab, row_number, "отправлено")
        return True
    except TelegramError as exc:
        logger.warning("Failed to send appointment to %s: %s", fallback, exc)
        _log_undelivered(
            sheets=sheets,
            undelivered_tab=undelivered_tab,
            zone=zone,
            store=store,
            username=username,
            kind=kind,
            reason=str(exc),
        )
        return False


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
) -> bool:
    chat_id = store.get_chat_id(username)
    fallback = username if username.startswith("@") or username.isdigit() else f"@{username}"
    try:
        await send_main_message(bot, chat_id or fallback)
        sheets.update_appointment_status(appointments_tab, row_number, "отправлено")
        if chat_id:
            store.set_reminder_context(chat_id, row_number, datetime.now(zone))
        return True
    except TelegramError as exc:
        logger.warning("Failed to send periodic reminder to %s: %s", fallback, exc)
        _log_undelivered(
            sheets=sheets,
            undelivered_tab=undelivered_tab,
            zone=zone,
            store=store,
            username=username,
            kind=f"{reminder_months}m",
            reason=str(exc),
        )
        return False


def _build_reschedule_url(dt: datetime) -> str:
    date_str = dt.strftime("%d.%m.%Y")
    text = f"Здравствуйте! Хочу перенести мою запись {date_str}"
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
            created_local = created.replace(tzinfo=zone) if created.tzinfo is None else created.astimezone(zone)
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
