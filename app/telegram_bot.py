from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.messages import (
    ADULT_SUBSCRIPTION_TEXT,
    CHILD_SUBSCRIPTION_TEXT,
    FLASH_WHITENING_TEXT,
    IMPLANT_CROWN_TEXT,
    ULTRASOUND_EXTRACTION_TEXT,
    build_adult_subscription_keyboard,
    build_child_subscription_keyboard,
    build_flash_contact_keyboard,
    build_implant_contact_keyboard,
    build_ultrasound_contact_keyboard,
    send_about_message,
    send_info_start_message,
    send_main_message,
    send_special_offers_message,
    send_start_message,
)
from app.scheduler import send_daily_messages
from app.sheets import SheetsClient
from app.storage import SQLiteStateStore

logger = logging.getLogger("golden-dent")

_CANCEL_REASON_LABELS = {
    "plans": "Изменились планы",
    "irrelevant": "Неактуально",
    "sick": "Заболел",
    "other": "Другое",
}
_PENDING_ACTION_COLLECT_FULL_NAME = "collect_full_name"


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
    application.add_handler(CommandHandler("test_reset", test_reset_cmd))
    application.add_handler(CommandHandler("whoami", whoami_cmd))

    application.add_handler(
        CallbackQueryHandler(remind_2w_cb, pattern=r"^remind_2w(?::\d+)?$")
    )
    application.add_handler(
        CallbackQueryHandler(not_ready_cb, pattern=r"^not_ready(?::\d+)?$")
    )
    application.add_handler(
        CallbackQueryHandler(confirm_appt_cb, pattern=r"^confirm_appt(?::\d+)?$")
    )
    application.add_handler(CallbackQueryHandler(cancel_appt_cb, pattern=r"^cancel_appt:\d+$"))
    application.add_handler(
        CallbackQueryHandler(
            cancel_reason_cb,
            pattern=r"^cancel_reason:\d+:(plans|irrelevant|sick|other)$",
        )
    )
    application.add_handler(CallbackQueryHandler(go_start_cb, pattern="^go_start$"))
    application.add_handler(CallbackQueryHandler(about_us_cb, pattern="^about_us$"))
    application.add_handler(CallbackQueryHandler(special_offers_cb, pattern="^special_offers$"))
    application.add_handler(CallbackQueryHandler(offer_adult_cb, pattern="^offer_adult$"))
    application.add_handler(CallbackQueryHandler(offer_child_cb, pattern="^offer_child$"))
    application.add_handler(CallbackQueryHandler(offer_implant_cb, pattern="^offer_implant$"))
    application.add_handler(
        CallbackQueryHandler(offer_ultrasound_cb, pattern="^offer_ultrasound$")
    )
    application.add_handler(CallbackQueryHandler(offer_flash_cb, pattern="^offer_flash$"))

    application.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return application


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.effective_user:
        return
    _record_user(update, context)
    await send_info_start_message(context.bot, update.effective_chat.id)
    full_name_requested = await _request_full_name_if_needed(update, context)
    if not full_name_requested:
        await _request_contact_if_needed(update, context)

    tz = ZoneInfo(context.application.bot_data["tz"])
    now = datetime.now(tz)
    store: SQLiteStateStore = context.application.bot_data["store"]
    if not store.mark_activated(update.effective_user.id, now):
        return

    scheduler = context.application.bot_data["scheduler"]
    scheduler.add_job(
        send_start_message,
        trigger="date",
        run_date=now + timedelta(days=3),
        id=f"start_followup_{update.effective_user.id}",
        replace_existing=True,
        args=[context.bot, update.effective_chat.id],
    )


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
    zone = ZoneInfo(tz)
    days_ahead = _parse_test_daily_days_ahead(context.args)
    target_date = (datetime.now(zone).date() + timedelta(days=days_ahead)).strftime("%d.%m.%Y")
    try:
        stats = await send_daily_messages(
            context.bot,
            sheets,
            tab,
            undelivered_tab,
            tz,
            store,
            appointment_days_ahead=days_ahead,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("test_daily failed")
        if update.effective_chat:
            await update.effective_chat.send_message(
                f"Ошибка /test_daily: {type(exc).__name__}: {exc}"
            )
        return
    if update.effective_chat:
        await update.effective_chat.send_message(
            "\n".join(
                [
                    "РўРµСЃС‚ РµР¶РµРґРЅРµРІРЅРѕР№ СЂР°СЃСЃС‹Р»РєРё Р·Р°РІРµСЂС€РµРЅ.",
                    f"Целевая дата: {target_date} (смещение: {days_ahead})",
                    f"РЎС‚СЂРѕРє РѕР±СЂР°Р±РѕС‚Р°РЅРѕ: {stats['rows_total']}",
                    f"РљР°РЅРґРёРґР°С‚С‹ (Р·Р°РїРёСЃСЊ РЅР° Р·Р°РІС‚СЂР°): {stats['appointment_candidates']}",
                    f"РљР°РЅРґРёРґР°С‚С‹ (С…РёСЂСѓСЂРі РЅР° Р·Р°РІС‚СЂР°): {stats['surgeon_candidates']}",
                    f"РљР°РЅРґРёРґР°С‚С‹ (РїРµСЂРёРѕРґРёС‡РµСЃРєРёРµ): {stats['periodic_candidates']}",
                    f"РЈСЃРїРµС€РЅРѕ РѕС‚РїСЂР°РІР»РµРЅРѕ: {stats['sent']}",
                    f"РћС€РёР±РѕРє РѕС‚РїСЂР°РІРєРё: {stats['failed']}",
                ]
            )
        )


def _parse_test_daily_days_ahead(args: list[str]) -> int:
    if not args:
        return 1
    value = args[0].strip().lower()
    aliases = {
        "today": 0,
        "сегодня": 0,
        "tomorrow": 1,
        "завтра": 1,
    }
    if value in aliases:
        return aliases[value]
    if value.startswith("+"):
        value = value[1:]
    if value.isdigit():
        return int(value)
    return 1


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
            reason = "OK: напоминание о записи на завтра"
        elif entry.surgeon_dt and entry.surgeon_dt.date() == tomorrow:
            reason = "OK: напоминание о плановом визите хирурга"
        elif entry_date + relativedelta(months=+entry.reminder_months) == today:
            reason = f"OK: {entry.reminder_months}-месячное напоминание"
        else:
            reason = "NO: сегодня не подходит ни одно условие"
        line = (
            f"{count}) row={entry.row_number} | "
            f"{entry.dt.strftime('%d.%m.%Y %H:%M')} | {entry.username} | {reason}"
        )
        lines.append(line)

    if count == 0:
        lines.append("Нет валидных строк (проверь формат даты и username).")

    await update.effective_chat.send_message("\n".join(lines))


async def test_reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_chat:
        return

    store: SQLiteStateStore = context.application.bot_data["store"]
    stats = store.reset_user_state(
        user_id=update.effective_user.id,
        chat_id=update.effective_chat.id,
        username=update.effective_user.username,
    )

    scheduler = context.application.bot_data["scheduler"]
    for job_id in (
        f"start_followup_{update.effective_user.id}",
        f"remind_{update.effective_chat.id}",
    ):
        job = scheduler.get_job(job_id)
        if job:
            scheduler.remove_job(job_id)

    if stats["client_map"] > 0:
        _sync_clients_sheet(context)

    await update.effective_chat.send_message(
        "\n".join(
            [
                "Тестовый сброс завершен.",
                f"Удалено записей: {stats['total']}",
                f"client_map={stats['client_map']}, user_activation={stats['user_activation']}, "
                f"pending_comment={stats['pending_comment']}, user_map={stats['user_map']}, "
                f"reminder_context={stats['reminder_context']}",
                "Для прохождения пути нового клиента отправьте /start.",
            ]
        )
    )


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
    await query.message.reply_text("Хорошо, вернёмся через 2 недели. До свидания, хорошего дня!")

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

    row_number, status_column = _resolve_status_target(
        query.data or "",
        query.message.chat.id,
        context,
    )
    if row_number:
        _set_appointment_status(
            context,
            row_number,
            "напомнить через 2 недели",
            status_column=status_column,
        )


async def not_ready_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message or not query.from_user:
        return
    _record_user(update, context)
    await query.answer()
    await query.message.reply_text("Подскажите, пожалуйста, почему не получается?")

    row_number, status_column = _resolve_status_target(
        query.data or "",
        query.message.chat.id,
        context,
    )
    store: SQLiteStateStore = context.application.bot_data["store"]
    tz = ZoneInfo(context.application.bot_data["tz"])
    username = f"@{query.from_user.username}" if query.from_user.username else f"id:{query.from_user.id}"
    store.set_pending(
        user_id=query.from_user.id,
        username=username,
        created_at=datetime.now(tz),
        action_type="not_ready_comment",
        appointment_row=row_number,
        status_column=status_column,
    )
    if row_number:
        _set_appointment_status(
            context,
            row_number,
            "не готов, ожидаем комментарий",
            status_column=status_column,
        )


async def confirm_appt_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    _record_user(update, context)
    await query.answer()
    await query.message.reply_text("Отлично, будем ждать Вас!")

    row_number = _parse_callback_row(query.data or "", "confirm_appt")
    if row_number:
        _set_appointment_status(context, row_number, "подтвердил")


async def cancel_appt_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    _record_user(update, context)
    await query.answer()

    row_number = _parse_callback_row(query.data or "", "cancel_appt")
    if not row_number:
        await query.message.reply_text("Не удалось определить запись для отмены.")
        return

    _set_appointment_status(context, row_number, "отменил")
    await query.message.reply_text(
        "Уточните, пожалуйста, причину отмены:",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "1. Изменились планы",
                        callback_data=f"cancel_reason:{row_number}:plans",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "2. Неактуально",
                        callback_data=f"cancel_reason:{row_number}:irrelevant",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "3. Заболел",
                        callback_data=f"cancel_reason:{row_number}:sick",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "4. Другое",
                        callback_data=f"cancel_reason:{row_number}:other",
                    )
                ],
            ]
        ),
    )


async def cancel_reason_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message or not query.from_user:
        return
    _record_user(update, context)
    await query.answer()

    row_number, reason_key = _parse_cancel_reason_callback(query.data or "")
    if not row_number or not reason_key:
        await query.message.reply_text("Не удалось определить причину отмены.")
        return

    reason_text = _CANCEL_REASON_LABELS.get(reason_key, "")
    if reason_key != "other":
        _set_appointment_cancel_reason(context, row_number, reason_text)
        await query.message.reply_text("Спасибо, отметили отмену записи.")
        return

    store: SQLiteStateStore = context.application.bot_data["store"]
    tz = ZoneInfo(context.application.bot_data["tz"])
    username = f"@{query.from_user.username}" if query.from_user.username else f"id:{query.from_user.id}"
    store.set_pending(
        user_id=query.from_user.id,
        username=username,
        created_at=datetime.now(tz),
        action_type="cancel_other_reason",
        appointment_row=row_number,
    )
    await query.message.reply_text("Напишите, пожалуйста, причину отмены в свободной форме.")


async def about_us_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    _record_user(update, context)
    await query.answer()
    await send_about_message(context.bot, query.message.chat.id)


async def go_start_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    _record_user(update, context)
    await query.answer()
    await send_info_start_message(context.bot, query.message.chat.id)


async def special_offers_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    _record_user(update, context)
    await query.answer()
    await send_special_offers_message(context.bot, query.message.chat.id)


async def offer_adult_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    _record_user(update, context)
    await query.answer()
    await query.message.reply_text(
        ADULT_SUBSCRIPTION_TEXT,
        reply_markup=build_adult_subscription_keyboard(),
    )


async def offer_child_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    _record_user(update, context)
    await query.answer()
    await query.message.reply_text(
        CHILD_SUBSCRIPTION_TEXT,
        reply_markup=build_child_subscription_keyboard(),
    )


async def offer_implant_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    _record_user(update, context)
    await query.answer()
    await query.message.reply_text(
        IMPLANT_CROWN_TEXT,
        reply_markup=build_implant_contact_keyboard(),
    )


async def offer_ultrasound_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    _record_user(update, context)
    await query.answer()
    await query.message.reply_text(
        ULTRASOUND_EXTRACTION_TEXT,
        reply_markup=build_ultrasound_contact_keyboard(),
    )


async def offer_flash_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    _record_user(update, context)
    await query.answer()
    await query.message.reply_text(
        FLASH_WHITENING_TEXT,
        reply_markup=build_flash_contact_keyboard(),
    )


async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    _record_user(update, context)
    contact = update.message.contact
    if not contact:
        return

    if contact.user_id and contact.user_id != update.effective_user.id:
        await update.message.reply_text(
            "Пожалуйста, отправьте свой номер через кнопку ниже.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    store: SQLiteStateStore = context.application.bot_data["store"]
    tz = ZoneInfo(context.application.bot_data["tz"])
    now = datetime.now(tz)
    user = update.effective_user
    existing = store.get_client(user.id)
    full_name = existing.full_name if existing else ""
    changed = store.upsert_client(
        user_id=user.id,
        username=user.username,
        full_name=full_name,
        phone=contact.phone_number,
        updated_at=now,
    )

    if changed:
        _sync_clients_sheet(context)

    await update.message.reply_text(
        "Спасибо! Номер сохранен.",
        reply_markup=ReplyKeyboardRemove(),
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    _record_user(update, context)
    text = update.message.text.strip()

    store: SQLiteStateStore = context.application.bot_data["store"]
    pending = store.pop_pending(update.effective_user.id)
    if pending:
        tz = ZoneInfo(context.application.bot_data["tz"])
        if pending.action_type == _PENDING_ACTION_COLLECT_FULL_NAME:
            full_name = _parse_full_name_segments(text)
            if not full_name:
                store.set_pending(
                    user_id=update.effective_user.id,
                    username=pending.username,
                    created_at=datetime.now(tz),
                    action_type=_PENDING_ACTION_COLLECT_FULL_NAME,
                )
                await update.message.reply_text(
                    "Пожалуйста, напишите ФИО в формате: Фамилия Имя Отчество."
                )
                return

            now = datetime.now(tz)
            profile = store.get_client(update.effective_user.id)
            phone = profile.phone if profile else ""
            changed = store.upsert_client(
                user_id=update.effective_user.id,
                username=update.effective_user.username,
                full_name=full_name,
                phone=phone,
                updated_at=now,
            )
            if changed:
                _sync_clients_sheet(context)
            await update.message.reply_text("Спасибо! ФИО сохранили.")
            await _request_contact_if_needed(update, context)
            return

        sheets: SheetsClient = context.application.bot_data["sheets"]
        now_str = datetime.now(tz).strftime("%d.%m.%Y %H:%M")
        profile = store.get_client(update.effective_user.id)
        full_name = profile.full_name if profile else ""
        phone = profile.phone if profile else ""

        if pending.action_type == "cancel_other_reason":
            if pending.appointment_row:
                _set_appointment_cancel_reason(context, pending.appointment_row, text)
                _set_appointment_status(
                    context,
                    pending.appointment_row,
                    "отменил",
                    status_column=pending.status_column,
                )
            sheets.append_comment(
                context.application.bot_data["config"].google_comments_tab,
                [now_str, pending.username, f"Отмена записи: {text}", full_name, phone],
            )
            await update.message.reply_text("Спасибо, причина отмены записана.")
            return

        sheets.append_comment(
            context.application.bot_data["config"].google_comments_tab,
            [now_str, pending.username, text, full_name, phone],
        )
        if pending.appointment_row:
            _set_appointment_status(
                context,
                pending.appointment_row,
                "не готов, комментарий",
                status_column=pending.status_column,
            )
        await update.message.reply_text("Спасибо, комментарий записан!")
        return

    if text.lower() == "пропустить":
        await update.message.reply_text("Хорошо, продолжим без номера.", reply_markup=ReplyKeyboardRemove())
        return


def _record_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user:
        return

    user = update.effective_user
    store: SQLiteStateStore = context.application.bot_data["store"]
    tz = ZoneInfo(context.application.bot_data["tz"])
    now = datetime.now(tz)

    if user.username:
        store.upsert_user(user.username, user.id, now)

    existing = store.get_client(user.id)
    full_name = existing.full_name if existing else ""
    phone = existing.phone if existing else ""
    changed = store.upsert_client(
        user_id=user.id,
        username=user.username,
        full_name=full_name,
        phone=phone,
        updated_at=now,
    )

    if changed:
        _sync_clients_sheet(context)


async def _request_contact_if_needed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_chat:
        return

    store: SQLiteStateStore = context.application.bot_data["store"]
    profile = store.get_client(update.effective_user.id)
    if not profile or not profile.full_name:
        return
    if profile and profile.phone:
        return

    keyboard = ReplyKeyboardMarkup(
        [
            [KeyboardButton("Поделиться номером", request_contact=True)],
            [KeyboardButton("Пропустить")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await update.effective_chat.send_message(
        "Для удобства связи можете отправить номер телефона кнопкой ниже.",
        reply_markup=keyboard,
    )


async def _request_full_name_if_needed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.effective_user or not update.effective_chat:
        return False

    store: SQLiteStateStore = context.application.bot_data["store"]
    profile = store.get_client(update.effective_user.id)
    if profile and profile.full_name:
        return False

    tz = ZoneInfo(context.application.bot_data["tz"])
    user = update.effective_user
    username = f"@{user.username}" if user.username else f"id:{user.id}"
    store.set_pending(
        user_id=user.id,
        username=username,
        created_at=datetime.now(tz),
        action_type=_PENDING_ACTION_COLLECT_FULL_NAME,
    )
    await update.effective_chat.send_message(
        "Пожалуйста, напишите ФИО в формате: Фамилия Имя Отчество."
    )
    return True


def _sync_clients_sheet(context: ContextTypes.DEFAULT_TYPE) -> None:
    sheets: SheetsClient = context.application.bot_data["sheets"]
    store: SQLiteStateStore = context.application.bot_data["store"]
    clients_tab = context.application.bot_data["config"].google_clients_tab
    try:
        sheets.sync_clients(clients_tab, store.list_clients())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to sync clients sheet %s: %s", clients_tab, exc)


def _parse_full_name_segments(text: str) -> str:
    normalized = " ".join(text.split())
    if not normalized:
        return ""
    parts = normalized.split(" ")
    if len(parts) < 2 or len(parts) > 4:
        return ""
    return normalized


def _resolve_status_target(
    callback_data: str,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> tuple[int | None, str]:
    for prefix in ("remind_2w", "not_ready"):
        row = _parse_callback_row(callback_data, prefix)
        if row:
            return row, "C"
    store: SQLiteStateStore = context.application.bot_data["store"]
    target = store.get_reminder_context_target(chat_id)
    if not target:
        return None, "C"
    return target


def _parse_callback_row(callback_data: str, prefix: str) -> int | None:
    if callback_data == prefix:
        return None
    if not callback_data.startswith(f"{prefix}:"):
        return None
    value = callback_data.split(":", maxsplit=1)[1]
    if not value.isdigit():
        return None
    return int(value)


def _parse_cancel_reason_callback(callback_data: str) -> tuple[int | None, str | None]:
    parts = callback_data.split(":")
    if len(parts) != 3:
        return None, None
    _, row_value, reason_key = parts
    if not row_value.isdigit():
        return None, None
    return int(row_value), reason_key


def _set_appointment_status(
    context: ContextTypes.DEFAULT_TYPE,
    row_number: int,
    status: str,
    status_column: str = "C",
) -> None:
    sheets: SheetsClient = context.application.bot_data["sheets"]
    tab = context.application.bot_data["config"].google_appointments_tab
    sheets.update_appointment_status(tab, row_number, status, status_column=status_column)


def _set_appointment_cancel_reason(
    context: ContextTypes.DEFAULT_TYPE,
    row_number: int,
    reason: str,
) -> None:
    sheets: SheetsClient = context.application.bot_data["sheets"]
    tab = context.application.bot_data["config"].google_appointments_tab
    sheets.update_appointment_cancel_reason(tab, row_number, reason)
