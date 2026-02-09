from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.messages import send_main_message, send_start_message
from app.sheets import SheetsClient
from app.storage import SQLiteStateStore
from app.scheduler import send_daily_messages


def build_application(
    bot_token: str,
    tz: str,
    sheets: SheetsClient,
    store: SQLiteStateStore,
    scheduler,
    config,
) -> Application:
    application = Application.builder().token(bot_token).build()
    application.bot_data["tz"] = tz
    application.bot_data["sheets"] = sheets
    application.bot_data["store"] = store
    application.bot_data["scheduler"] = scheduler
    application.bot_data["config"] = config

    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("test_main", test_main_cmd))
    application.add_handler(CommandHandler("test_daily", test_daily_cmd))
    application.add_handler(CommandHandler("test_daily_debug", test_daily_debug_cmd))
    application.add_handler(CommandHandler("whoami", whoami_cmd))
    application.add_handler(CallbackQueryHandler(remind_2w_cb, pattern="^remind_2w$"))
    application.add_handler(CallbackQueryHandler(not_ready_cb, pattern="^not_ready$"))
    application.add_handler(CallbackQueryHandler(confirm_appt_cb, pattern="^confirm_appt$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return application


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat:
        return
    _record_user(update, context)
    await send_start_message(context.bot, update.effective_chat.id)


async def test_main_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat:
        return
    _record_user(update, context)
    await send_start_message(context.bot, update.effective_chat.id)


async def test_daily_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _record_user(update, context)
    sheets: SheetsClient = context.application.bot_data["sheets"]
    tz = context.application.bot_data["tz"]
    tab = context.application.bot_data["config"].google_appointments_tab
    undelivered_tab = context.application.bot_data["config"].google_undelivered_tab
    store: SQLiteStateStore = context.application.bot_data["store"]
    await send_daily_messages(context.bot, sheets, tab, undelivered_tab, tz, store)


async def test_daily_debug_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat:
        return
    _record_user(update, context)
    sheets: SheetsClient = context.application.bot_data["sheets"]
    tz = context.application.bot_data["tz"]
    tab = context.application.bot_data["config"].google_appointments_tab
    zone = ZoneInfo(tz)
    today = datetime.now(zone).date()
    tomorrow = today + timedelta(days=1)

    lines = [
        f"Сегодня (Нск): {today.strftime('%d.%m.%Y')}",
        f"Завтра (Нск): {tomorrow.strftime('%d.%m.%Y')}",
        f"Лист: {tab}",
        "",
    ]

    count = 0
    for entry in sheets.iter_entries(tab):
        count += 1
        entry_date = entry.dt.date()
        if entry_date == tomorrow:
            reason = "OK: напоминание на завтра"
        elif entry_date + relativedelta(months=+6) == today:
            reason = "OK: 6-месячное напоминание"
        else:
            reason = "NO: не завтра и не 6 месяцев"
        lines.append(f"{count}) {entry.dt.strftime('%d.%m.%Y %H:%M')} | {entry.username} | {reason}")

    if count == 0:
        lines.append("Нет валидных строк (проверь формат даты и username).")

    await update.effective_chat.send_message("\n".join(lines))


async def whoami_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_chat:
        return
    _record_user(update, context)
    user = update.effective_user
    username = f"@{user.username}" if user.username else "нет username"
    await update.effective_chat.send_message(f"Ваш username: {username}")


async def remind_2w_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    _record_user(update, context)
    await query.answer()
    await query.message.reply_text("Хорошо, вернёмся через 2 недели")

    scheduler = context.application.bot_data["scheduler"]
    tz = ZoneInfo(context.application.bot_data["tz"])
    run_date = datetime.now(tz) + timedelta(days=14)
    chat_id = query.message.chat.id
    job_id = f"remind_{chat_id}"
    scheduler.add_job(
        send_main_message,
        trigger="date",
        run_date=run_date,
        id=job_id,
        replace_existing=True,
        args=[context.bot, chat_id],
    )


async def not_ready_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    _record_user(update, context)
    await query.answer()
    await query.message.reply_text("Подскажите, пожалуйста, почему не получается?")

    store: SQLiteStateStore = context.application.bot_data["store"]
    tz = ZoneInfo(context.application.bot_data["tz"])
    user = query.from_user
    username = f"@{user.username}" if user and user.username else f"id:{user.id}"
    store.set_pending(user.id, username, datetime.now(tz))


async def confirm_appt_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    _record_user(update, context)
    await query.answer()
    await query.message.reply_text("Отлично, будем ждать Вас!")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    _record_user(update, context)
    store: SQLiteStateStore = context.application.bot_data["store"]
    pending = store.pop_pending(update.effective_user.id)
    if not pending:
        return

    sheets: SheetsClient = context.application.bot_data["sheets"]
    tz = ZoneInfo(context.application.bot_data["tz"])
    now_str = datetime.now(tz).strftime("%d.%m.%Y %H:%M")
    comment = update.message.text.strip()
    sheets.append_comment(
        context.application.bot_data["config"].google_comments_tab,
        [now_str, pending.username, comment],
    )
    await update.message.reply_text("Спасибо, комментарий записан!")


def _record_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user:
        return
    user = update.effective_user
    if not user.username:
        return
    store: SQLiteStateStore = context.application.bot_data["store"]
    tz = ZoneInfo(context.application.bot_data["tz"])
    store.upsert_user(user.username, user.id, datetime.now(tz))
