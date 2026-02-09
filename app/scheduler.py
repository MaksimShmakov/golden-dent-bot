from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dateutil.relativedelta import relativedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
import logging

from app.sheets import SheetsClient
from app.storage import SQLiteStateStore
from app.messages import send_main_message

logger = logging.getLogger("golden-dent")

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


async def send_daily_messages(
    bot, sheets: SheetsClient, tab_name: str, undelivered_tab: str, tz: str, store: SQLiteStateStore
) -> None:
    zone = ZoneInfo(tz)
    today = datetime.now(zone).date()
    tomorrow = today + timedelta(days=1)

    for entry in sheets.iter_entries(tab_name):
        entry_date = entry.dt.date()

        if entry_date == tomorrow:
            await _send_appointment_message(
                bot, sheets, undelivered_tab, entry.username, entry.dt, zone, store
            )
            continue

        if entry_date + relativedelta(months=+6) == today:
            await _send_6m_message(bot, sheets, undelivered_tab, entry.username, zone, store)


async def _send_appointment_message(
    bot,
    sheets: SheetsClient,
    undelivered_tab: str,
    username: str,
    dt: datetime,
    zone,
    store: SQLiteStateStore,
) -> None:
    local_dt = dt.replace(tzinfo=zone) if dt.tzinfo is None else dt.astimezone(zone)
    date_str = local_dt.strftime("%d.%m.%Y")
    time_str = local_dt.strftime("%H:%M")
    text = (
        "Здравствуйте! Вы записаны на завтра "
        f"{date_str}г в клинику «Голден Дент» на прием в {time_str} 🕥"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Подтвердить запись", callback_data="confirm_appt")],
            [InlineKeyboardButton("Перенести запись", url="https://t.me/GoldenDentNSK")],
        ]
    )
    chat_id = store.get_chat_id(username)
    fallback = username if username.startswith("@") or username.isdigit() else f"@{username}"
    try:
        await bot.send_message(chat_id=chat_id or fallback, text=text, reply_markup=keyboard)
    except TelegramError as exc:
        logger.warning("Failed to send appointment to %s: %s", fallback, exc)
        if "Chat not found" in str(exc):
            _log_undelivered(
                sheets,
                undelivered_tab,
                zone,
                username,
                "appointment",
                str(exc),
            )
        return


async def _send_6m_message(
    bot,
    sheets: SheetsClient,
    undelivered_tab: str,
    username: str,
    zone,
    store: SQLiteStateStore,
) -> None:
    chat_id = store.get_chat_id(username)
    fallback = username if username.startswith("@") or username.isdigit() else f"@{username}"
    try:
        await send_main_message(bot, chat_id or fallback)
    except TelegramError as exc:
        logger.warning("Failed to send 6m reminder to %s: %s", fallback, exc)
        if "Chat not found" in str(exc):
            _log_undelivered(
                sheets,
                undelivered_tab,
                zone,
                username,
                "6m",
                str(exc),
            )
        return


def _log_undelivered(
    sheets: SheetsClient,
    undelivered_tab: str,
    zone,
    username: str,
    kind: str,
    reason: str,
) -> None:
    now_str = datetime.now(zone).strftime("%d.%m.%Y %H:%M")
    sheets.append_undelivered(undelivered_tab, [now_str, username, kind, reason])
