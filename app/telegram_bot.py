from __future__ import annotations

import logging
from datetime import datetime, timedelta
from urllib.parse import urlparse
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
from telegram.error import TelegramError
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
    SPECIAL_OFFERS_HEADER,
    ULTRASOUND_EXTRACTION_TEXT,
    build_adult_subscription_keyboard,
    build_child_subscription_keyboard,
    build_flash_contact_keyboard,
    build_implant_contact_keyboard,
    build_special_offers_keyboard,
    build_ultrasound_contact_keyboard,
    send_about_message,
    send_info_start_message,
    send_main_message,
    send_special_offers_message,
    send_start_message,
)
from app.scheduler import send_daily_messages
from app.sheets import SheetsClient
from app.storage import OfferTemplate, SQLiteStateStore

logger = logging.getLogger("golden-dent")

_CANCEL_REASON_LABELS = {
    "plans": "Изменились планы",
    "irrelevant": "Неактуально",
    "sick": "Заболел",
    "other": "Другое",
}
_PENDING_ACTION_COLLECT_FULL_NAME = "collect_full_name"
_BROADCAST_STATE_KEY = "broadcast_state"
_BROADCAST_DRAFT_KEY = "broadcast_draft"
_OFFERS_ADMIN_STATE_KEY = "offers_admin_state"
_OFFERS_ADMIN_DRAFT_KEY = "offers_admin_draft"
_ADMINS_CACHE_KEY = "admin_usernames_cache"
_ADMINS_CACHE_AT_KEY = "admin_usernames_cache_at"
_ADMINS_CACHE_TTL = timedelta(seconds=60)


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
    store.ensure_special_offers_defaults(
        header=SPECIAL_OFFERS_HEADER,
        offers=_build_default_offer_templates(),
    )

    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("test_main", test_main_cmd))
    application.add_handler(CommandHandler("test_daily", test_daily_cmd))
    application.add_handler(CommandHandler("test_daily_debug", test_daily_debug_cmd))
    application.add_handler(CommandHandler("test_reset", test_reset_cmd))
    application.add_handler(CommandHandler("broadcast", broadcast_cmd))
    application.add_handler(CommandHandler("broadcast_cancel", broadcast_cancel_cmd))
    application.add_handler(CommandHandler("offers_admin", offers_admin_cmd))
    application.add_handler(CommandHandler("offers_admin_cancel", offers_admin_cancel_cmd))
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
    application.add_handler(
        CallbackQueryHandler(
            offers_admin_action_cb,
            pattern=r"^offers_admin:(header|add|edit|delete|preview|done)$",
        )
    )
    application.add_handler(
        CallbackQueryHandler(offers_admin_edit_select_cb, pattern=r"^offers_admin_edit:\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(offers_admin_delete_cb, pattern=r"^offers_admin_delete:\d+$")
    )
    application.add_handler(CallbackQueryHandler(offer_dynamic_cb, pattern=r"^offer_dynamic:\d+$"))
    application.add_handler(CallbackQueryHandler(offer_adult_cb, pattern="^offer_adult$"))
    application.add_handler(CallbackQueryHandler(offer_child_cb, pattern="^offer_child$"))
    application.add_handler(CallbackQueryHandler(offer_implant_cb, pattern="^offer_implant$"))
    application.add_handler(
        CallbackQueryHandler(offer_ultrasound_cb, pattern="^offer_ultrasound$")
    )
    application.add_handler(CallbackQueryHandler(offer_flash_cb, pattern="^offer_flash$"))

    application.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
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


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_chat:
        return
    _record_user(update, context)
    if not await _ensure_admin(update, context):
        return
    _clear_offers_admin_flow(context)
    _start_broadcast_flow(context)
    await update.effective_chat.send_message(
        "Шаг 1/5. Пришлите фото для рассылки или напишите `пропустить`.",
        parse_mode=None,
    )


async def broadcast_cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.effective_user:
        return
    _record_user(update, context)
    if not await _ensure_admin(update, context):
        return
    if _clear_broadcast_flow(context):
        await update.effective_chat.send_message("Кастомная рассылка отменена.")
        return
    await update.effective_chat.send_message("Сейчас нет активной кастомной рассылки.")


async def offers_admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.effective_user:
        return
    _record_user(update, context)
    if not await _ensure_admin(update, context):
        return
    _clear_broadcast_flow(context)
    _clear_offers_admin_flow(context)
    await _send_offers_admin_panel(update.effective_chat.id, context, include_hint=True)


async def offers_admin_cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.effective_user:
        return
    _record_user(update, context)
    if not await _ensure_admin(update, context):
        return
    if _clear_offers_admin_flow(context):
        await update.effective_chat.send_message("Редактирование акций отменено.")
        return
    await update.effective_chat.send_message("Сейчас нет активного режима редактирования акций.")


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
    await _send_special_offers_menu(context.bot, query.message.chat.id, context)


async def offer_dynamic_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    _record_user(update, context)
    await query.answer()

    offer_id = _parse_callback_row(query.data or "", "offer_dynamic")
    if not offer_id:
        await query.message.reply_text("Не удалось определить акцию.")
        return
    await _send_offer_template_by_id(
        context.bot,
        query.message.chat.id,
        offer_id,
        context,
    )


async def offer_adult_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    _record_user(update, context)
    await query.answer()
    await _send_legacy_offer(
        context.bot,
        query.message.chat.id,
        context,
        legacy_key="adult",
        fallback_text=ADULT_SUBSCRIPTION_TEXT,
        fallback_keyboard=build_adult_subscription_keyboard(),
    )


async def offer_child_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    _record_user(update, context)
    await query.answer()
    await _send_legacy_offer(
        context.bot,
        query.message.chat.id,
        context,
        legacy_key="child",
        fallback_text=CHILD_SUBSCRIPTION_TEXT,
        fallback_keyboard=build_child_subscription_keyboard(),
    )


async def offer_implant_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    _record_user(update, context)
    await query.answer()
    await _send_legacy_offer(
        context.bot,
        query.message.chat.id,
        context,
        legacy_key="implant",
        fallback_text=IMPLANT_CROWN_TEXT,
        fallback_keyboard=build_implant_contact_keyboard(),
    )


async def offer_ultrasound_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    _record_user(update, context)
    await query.answer()
    await _send_legacy_offer(
        context.bot,
        query.message.chat.id,
        context,
        legacy_key="ultrasound",
        fallback_text=ULTRASOUND_EXTRACTION_TEXT,
        fallback_keyboard=build_ultrasound_contact_keyboard(),
    )


async def offer_flash_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    _record_user(update, context)
    await query.answer()
    await _send_legacy_offer(
        context.bot,
        query.message.chat.id,
        context,
        legacy_key="flash",
        fallback_text=FLASH_WHITENING_TEXT,
        fallback_keyboard=build_flash_contact_keyboard(),
    )


async def offers_admin_action_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    _record_user(update, context)
    if not await _ensure_admin_query(query, context):
        return
    await query.answer()

    action = (query.data or "").split(":", maxsplit=1)[1]
    store: SQLiteStateStore = context.application.bot_data["store"]

    if action == "header":
        _set_offers_admin_state(context, "header")
        context.user_data[_OFFERS_ADMIN_DRAFT_KEY] = {}
        await query.message.reply_text("Отправьте новый заголовок для сообщения с акциями.")
        return

    if action == "add":
        _set_offers_admin_state(context, "add_button_text")
        context.user_data[_OFFERS_ADMIN_DRAFT_KEY] = {
            "mode": "add",
            "button_text": "",
            "message_text": "",
            "action_buttons": [],
        }
        await query.message.reply_text("Введите название кнопки новой акции.")
        return

    if action == "preview":
        await _send_special_offers_menu(context.bot, query.message.chat.id, context)
        await _send_offers_admin_panel(query.message.chat.id, context)
        return

    if action == "done":
        _clear_offers_admin_flow(context)
        await query.message.reply_text("Редактирование акций завершено.")
        return

    offers = store.list_offer_templates()
    if not offers:
        await query.message.reply_text("Пока нет акций для редактирования.")
        return

    if action == "edit":
        await query.message.reply_text(
            "Выберите акцию для изменения:",
            reply_markup=_build_offers_admin_offer_list_keyboard(offers, mode="edit"),
        )
        return

    if action == "delete":
        await query.message.reply_text(
            "Выберите акцию для удаления:",
            reply_markup=_build_offers_admin_offer_list_keyboard(offers, mode="delete"),
        )
        return


async def offers_admin_edit_select_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    _record_user(update, context)
    if not await _ensure_admin_query(query, context):
        return
    await query.answer()

    offer_id = _parse_callback_row(query.data or "", "offers_admin_edit")
    if not offer_id:
        await query.message.reply_text("Не удалось определить акцию.")
        return

    store: SQLiteStateStore = context.application.bot_data["store"]
    offer = store.get_offer_template(offer_id)
    if not offer:
        await query.message.reply_text("Акция не найдена.")
        return

    context.user_data[_OFFERS_ADMIN_DRAFT_KEY] = {
        "mode": "edit",
        "offer_id": offer.id,
        "button_text": offer.button_text,
        "message_text": offer.message_text,
        "action_buttons": offer.action_buttons,
    }
    _set_offers_admin_state(context, "edit_button_text")
    await query.message.reply_text(
        "Введите новый текст кнопки акции или напишите `пропустить`.",
    )


async def offers_admin_delete_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    _record_user(update, context)
    if not await _ensure_admin_query(query, context):
        return
    await query.answer()

    offer_id = _parse_callback_row(query.data or "", "offers_admin_delete")
    if not offer_id:
        await query.message.reply_text("Не удалось определить акцию.")
        return

    store: SQLiteStateStore = context.application.bot_data["store"]
    if not store.delete_offer_template(offer_id):
        await query.message.reply_text("Акция не найдена или уже удалена.")
        return
    await query.message.reply_text("Акция удалена.")
    await _send_offers_admin_panel(query.message.chat.id, context)


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


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    _record_user(update, context)
    state = _get_broadcast_state(context)
    if not state:
        return
    if state != "photo":
        await update.message.reply_text("Сейчас ожидаю текстовый ответ. Если нужно прервать, /broadcast_cancel.")
        return

    if not update.message.photo:
        await update.message.reply_text("Не удалось получить фото. Пришлите изображение еще раз.")
        return

    draft = _get_broadcast_draft(context)
    draft["photo_file_id"] = update.message.photo[-1].file_id
    _set_broadcast_state(context, "text")
    await update.message.reply_text("Шаг 2/5. Напишите текст рассылки.")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    _record_user(update, context)
    text = update.message.text.strip()

    if await _handle_offers_admin_text(update, context, text):
        return

    if await _handle_broadcast_text(update, context, text):
        return

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


def _build_default_offer_templates() -> list[dict[str, object]]:
    labels = [row[0].text for row in build_special_offers_keyboard().inline_keyboard if row]
    adult_label = labels[0] if len(labels) > 0 else "Акция 1"
    child_label = labels[1] if len(labels) > 1 else "Акция 2"
    implant_label = labels[2] if len(labels) > 2 else "Акция 3"
    ultrasound_label = labels[3] if len(labels) > 3 else "Акция 4"
    flash_label = labels[4] if len(labels) > 4 else "Акция 5"
    return [
        {
            "legacy_key": "adult",
            "button_text": adult_label,
            "message_text": ADULT_SUBSCRIPTION_TEXT,
            "action_buttons": _extract_offer_url_buttons(build_adult_subscription_keyboard()),
        },
        {
            "legacy_key": "child",
            "button_text": child_label,
            "message_text": CHILD_SUBSCRIPTION_TEXT,
            "action_buttons": _extract_offer_url_buttons(build_child_subscription_keyboard()),
        },
        {
            "legacy_key": "implant",
            "button_text": implant_label,
            "message_text": IMPLANT_CROWN_TEXT,
            "action_buttons": _extract_offer_url_buttons(build_implant_contact_keyboard()),
        },
        {
            "legacy_key": "ultrasound",
            "button_text": ultrasound_label,
            "message_text": ULTRASOUND_EXTRACTION_TEXT,
            "action_buttons": _extract_offer_url_buttons(build_ultrasound_contact_keyboard()),
        },
        {
            "legacy_key": "flash",
            "button_text": flash_label,
            "message_text": FLASH_WHITENING_TEXT,
            "action_buttons": _extract_offer_url_buttons(build_flash_contact_keyboard()),
        },
    ]


def _extract_offer_url_buttons(keyboard: InlineKeyboardMarkup) -> list[tuple[str, str]]:
    buttons: list[tuple[str, str]] = []
    for row in keyboard.inline_keyboard:
        for button in row:
            if button.url:
                buttons.append((button.text, button.url))
    return buttons


def _build_special_offers_dynamic_keyboard(offers: list[OfferTemplate]) -> InlineKeyboardMarkup:
    if not offers:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("В начало", callback_data="go_start")]]
        )
    rows = [
        [InlineKeyboardButton(offer.button_text, callback_data=f"offer_dynamic:{offer.id}")]
        for offer in offers
    ]
    return InlineKeyboardMarkup(rows)


def _build_offer_actions_keyboard(action_buttons: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(label, url=url)] for label, url in action_buttons]
    rows.append([InlineKeyboardButton("В начало", callback_data="go_start")])
    return InlineKeyboardMarkup(rows)


async def _send_offer_template_payload(bot, chat_id: int, offer: OfferTemplate) -> None:
    await bot.send_message(
        chat_id=chat_id,
        text=offer.message_text,
        reply_markup=_build_offer_actions_keyboard(offer.action_buttons),
    )


async def _send_offer_template_by_id(
    bot,
    chat_id: int,
    offer_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    store: SQLiteStateStore = context.application.bot_data["store"]
    offer = store.get_offer_template(offer_id)
    if not offer:
        await bot.send_message(chat_id=chat_id, text="Акция не найдена.")
        return
    await _send_offer_template_payload(bot, chat_id, offer)


async def _send_legacy_offer(
    bot,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    legacy_key: str,
    fallback_text: str,
    fallback_keyboard: InlineKeyboardMarkup,
) -> None:
    store: SQLiteStateStore = context.application.bot_data["store"]
    offer = store.get_offer_template_by_legacy_key(legacy_key)
    if offer:
        await _send_offer_template_payload(bot, chat_id, offer)
        return
    await bot.send_message(
        chat_id=chat_id,
        text=fallback_text,
        reply_markup=fallback_keyboard,
    )


async def _send_special_offers_menu(
    bot,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    store: SQLiteStateStore = context.application.bot_data["store"]
    offers = store.list_offer_templates()
    await send_special_offers_message(
        bot,
        chat_id,
        header=store.get_special_offers_header(SPECIAL_OFFERS_HEADER),
        keyboard=_build_special_offers_dynamic_keyboard(offers),
    )


def _build_offers_admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Изменить заголовок", callback_data="offers_admin:header")],
            [InlineKeyboardButton("Добавить акцию", callback_data="offers_admin:add")],
            [InlineKeyboardButton("Изменить акцию", callback_data="offers_admin:edit")],
            [InlineKeyboardButton("Удалить акцию", callback_data="offers_admin:delete")],
            [InlineKeyboardButton("Предпросмотр", callback_data="offers_admin:preview")],
            [InlineKeyboardButton("Завершить", callback_data="offers_admin:done")],
        ]
    )


def _build_offers_admin_offer_list_keyboard(
    offers: list[OfferTemplate],
    mode: str,
) -> InlineKeyboardMarkup:
    prefix = "offers_admin_edit" if mode == "edit" else "offers_admin_delete"
    rows = [
        [
            InlineKeyboardButton(
                f"{index}. {offer.button_text}",
                callback_data=f"{prefix}:{offer.id}",
            )
        ]
        for index, offer in enumerate(offers, start=1)
    ]
    rows.append([InlineKeyboardButton("Завершить", callback_data="offers_admin:done")])
    return InlineKeyboardMarkup(rows)


async def _send_offers_admin_panel(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    include_hint: bool = False,
) -> None:
    store: SQLiteStateStore = context.application.bot_data["store"]
    offers = store.list_offer_templates()
    lines = [
        "Панель управления акциями.",
        f"Акций в меню: {len(offers)}",
    ]
    if include_hint:
        lines.append("Выберите действие кнопками ниже.")
    await context.bot.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        reply_markup=_build_offers_admin_panel_keyboard(),
    )


def _set_offers_admin_state(context: ContextTypes.DEFAULT_TYPE, state: str) -> None:
    context.user_data[_OFFERS_ADMIN_STATE_KEY] = state


def _get_offers_admin_state(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    state = context.user_data.get(_OFFERS_ADMIN_STATE_KEY)
    return state if isinstance(state, str) else None


def _get_offers_admin_draft(context: ContextTypes.DEFAULT_TYPE) -> dict:
    draft = context.user_data.get(_OFFERS_ADMIN_DRAFT_KEY)
    if isinstance(draft, dict):
        return draft
    context.user_data[_OFFERS_ADMIN_DRAFT_KEY] = {}
    return context.user_data[_OFFERS_ADMIN_DRAFT_KEY]


def _clear_offers_admin_flow(context: ContextTypes.DEFAULT_TYPE) -> bool:
    had_state = bool(context.user_data.pop(_OFFERS_ADMIN_STATE_KEY, None))
    had_draft = bool(context.user_data.pop(_OFFERS_ADMIN_DRAFT_KEY, None))
    return had_state or had_draft


def _normalize_admin_username(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        return ""
    if not normalized.startswith("@"):
        normalized = f"@{normalized}"
    return normalized


def _get_sheet_admin_usernames(context: ContextTypes.DEFAULT_TYPE) -> set[str]:
    bot_data = context.application.bot_data
    cached_at = bot_data.get(_ADMINS_CACHE_AT_KEY)
    cached_usernames = bot_data.get(_ADMINS_CACHE_KEY)
    now = datetime.utcnow()

    if isinstance(cached_at, datetime) and isinstance(cached_usernames, set):
        if now - cached_at <= _ADMINS_CACHE_TTL:
            return cached_usernames

    sheets: SheetsClient = bot_data["sheets"]
    admins_tab = bot_data["config"].google_admins_tab
    try:
        usernames = {
            normalized
            for username in sheets.list_admin_usernames(admins_tab)
            if (normalized := _normalize_admin_username(username))
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load admin usernames from sheet %s: %s", admins_tab, exc)
        return cached_usernames if isinstance(cached_usernames, set) else set()

    bot_data[_ADMINS_CACHE_KEY] = usernames
    bot_data[_ADMINS_CACHE_AT_KEY] = now
    return usernames


def _is_admin_user(username: str | None, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not username:
        return False
    normalized = _normalize_admin_username(username)
    return normalized in _get_sheet_admin_usernames(context)


async def _ensure_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    chat = update.effective_chat
    if user and _is_admin_user(user.username, context):
        return True
    if chat:
        await chat.send_message("Команда доступна только администраторам.")
    return False


async def _ensure_admin_query(query, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if query.from_user and _is_admin_user(query.from_user.username, context):
        return True
    await query.answer("Только для администраторов.", show_alert=True)
    return False


async def _handle_offers_admin_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> bool:
    state = _get_offers_admin_state(context)
    if not state or not update.message:
        return False

    if not await _ensure_admin(update, context):
        _clear_offers_admin_flow(context)
        return True

    store: SQLiteStateStore = context.application.bot_data["store"]
    draft = _get_offers_admin_draft(context)
    lowered = text.strip().lower()
    skip_values = {"пропустить", "skip"}
    cancel_values = {"отмена", "cancel", "/offers_admin_cancel"}
    yes_values = {"да", "yes", "y"}
    no_values = {"нет", "no", "n"}

    if lowered in cancel_values:
        _clear_offers_admin_flow(context)
        await update.message.reply_text("Редактирование акций отменено.")
        return True

    if state == "header":
        if not text:
            await update.message.reply_text("Заголовок пустой. Отправьте текст заголовка.")
            return True
        store.set_special_offers_header(text)
        _clear_offers_admin_flow(context)
        await update.message.reply_text("Заголовок обновлён.")
        if update.effective_chat:
            await _send_offers_admin_panel(update.effective_chat.id, context)
        return True

    if state == "add_button_text":
        if not text:
            await update.message.reply_text("Название кнопки не может быть пустым.")
            return True
        draft["button_text"] = text
        _set_offers_admin_state(context, "add_message_text")
        await update.message.reply_text("Отправьте полный текст сообщения для этой акции.")
        return True

    if state == "add_message_text":
        if not text:
            await update.message.reply_text("Текст сообщения не может быть пустым.")
            return True
        draft["message_text"] = text
        _set_offers_admin_state(context, "add_buttons_choice")
        await update.message.reply_text("Нужны кнопки действий? Ответьте `да` или `нет`.")
        return True

    if state == "add_buttons_choice":
        if lowered in no_values:
            store.add_offer_template(
                button_text=str(draft.get("button_text", "")),
                message_text=str(draft.get("message_text", "")),
                action_buttons=[],
            )
            _clear_offers_admin_flow(context)
            await update.message.reply_text("Акция добавлена.")
            if update.effective_chat:
                await _send_offers_admin_panel(update.effective_chat.id, context)
            return True
        if lowered in yes_values:
            _set_offers_admin_state(context, "add_buttons_input")
            await update.message.reply_text(
                "Отправьте кнопки, каждая с новой строки:\n"
                "Текст кнопки | https://example.com\n"
                "Или напишите `пропустить`.",
            )
            return True
        await update.message.reply_text("Ответьте `да` или `нет`.")
        return True

    if state == "add_buttons_input":
        action_buttons: list[tuple[str, str]]
        if lowered in skip_values:
            action_buttons = []
        else:
            action_buttons, error = _parse_broadcast_buttons(text)
            if error:
                await update.message.reply_text(error)
                return True
        store.add_offer_template(
            button_text=str(draft.get("button_text", "")),
            message_text=str(draft.get("message_text", "")),
            action_buttons=action_buttons,
        )
        _clear_offers_admin_flow(context)
        await update.message.reply_text("Акция добавлена.")
        if update.effective_chat:
            await _send_offers_admin_panel(update.effective_chat.id, context)
        return True

    if state == "edit_button_text":
        if lowered not in skip_values:
            if not text:
                await update.message.reply_text(
                    "Название кнопки не может быть пустым. Введите текст или `пропустить`."
                )
                return True
            draft["button_text"] = text
        _set_offers_admin_state(context, "edit_message_text")
        await update.message.reply_text("Введите новый текст сообщения или `пропустить`.")
        return True

    if state == "edit_message_text":
        if lowered not in skip_values:
            if not text:
                await update.message.reply_text(
                    "Текст сообщения не может быть пустым. Введите текст или `пропустить`."
                )
                return True
            draft["message_text"] = text
        _set_offers_admin_state(context, "edit_buttons_choice")
        await update.message.reply_text(
            "Что сделать с кнопками действий?\n"
            "`пропустить` - оставить как есть\n"
            "`удалить` - убрать все кнопки\n"
            "`изменить` - задать новые",
        )
        return True

    if state == "edit_buttons_choice":
        offer_id = int(draft.get("offer_id", 0))
        if not offer_id:
            _clear_offers_admin_flow(context)
            await update.message.reply_text("Акция не найдена, начните заново через /offers_admin.")
            return True

        if lowered in skip_values:
            store.update_offer_template(
                offer_id,
                button_text=str(draft.get("button_text", "")),
                message_text=str(draft.get("message_text", "")),
            )
            _clear_offers_admin_flow(context)
            await update.message.reply_text("Акция обновлена.")
            if update.effective_chat:
                await _send_offers_admin_panel(update.effective_chat.id, context)
            return True
        if lowered == "удалить":
            store.update_offer_template(
                offer_id,
                button_text=str(draft.get("button_text", "")),
                message_text=str(draft.get("message_text", "")),
                action_buttons=[],
            )
            _clear_offers_admin_flow(context)
            await update.message.reply_text("Акция обновлена.")
            if update.effective_chat:
                await _send_offers_admin_panel(update.effective_chat.id, context)
            return True
        if lowered == "изменить":
            _set_offers_admin_state(context, "edit_buttons_input")
            await update.message.reply_text(
                "Отправьте кнопки, каждая с новой строки:\n"
                "Текст кнопки | https://example.com\n"
                "Или `пропустить`, чтобы оставить текущие.",
            )
            return True
        await update.message.reply_text("Напишите `пропустить`, `удалить` или `изменить`.")
        return True

    if state == "edit_buttons_input":
        offer_id = int(draft.get("offer_id", 0))
        if not offer_id:
            _clear_offers_admin_flow(context)
            await update.message.reply_text("Акция не найдена, начните заново через /offers_admin.")
            return True

        action_buttons = draft.get("action_buttons", [])
        if lowered not in skip_values:
            action_buttons, error = _parse_broadcast_buttons(text)
            if error:
                await update.message.reply_text(error)
                return True

        store.update_offer_template(
            offer_id,
            button_text=str(draft.get("button_text", "")),
            message_text=str(draft.get("message_text", "")),
            action_buttons=action_buttons,
        )
        _clear_offers_admin_flow(context)
        await update.message.reply_text("Акция обновлена.")
        if update.effective_chat:
            await _send_offers_admin_panel(update.effective_chat.id, context)
        return True

    return False


def _start_broadcast_flow(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data[_BROADCAST_DRAFT_KEY] = {
        "photo_file_id": None,
        "text": "",
        "buttons": [],
        "usernames": [],
    }
    _set_broadcast_state(context, "photo")


def _clear_broadcast_flow(context: ContextTypes.DEFAULT_TYPE) -> bool:
    had_state = bool(context.user_data.pop(_BROADCAST_STATE_KEY, None))
    had_draft = bool(context.user_data.pop(_BROADCAST_DRAFT_KEY, None))
    return had_state or had_draft


def _set_broadcast_state(context: ContextTypes.DEFAULT_TYPE, state: str) -> None:
    context.user_data[_BROADCAST_STATE_KEY] = state


def _get_broadcast_state(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    state = context.user_data.get(_BROADCAST_STATE_KEY)
    return state if isinstance(state, str) else None


def _get_broadcast_draft(context: ContextTypes.DEFAULT_TYPE) -> dict:
    draft = context.user_data.get(_BROADCAST_DRAFT_KEY)
    if isinstance(draft, dict):
        return draft
    context.user_data[_BROADCAST_DRAFT_KEY] = {
        "photo_file_id": None,
        "text": "",
        "buttons": [],
        "usernames": [],
    }
    return context.user_data[_BROADCAST_DRAFT_KEY]


async def _handle_broadcast_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> bool:
    state = _get_broadcast_state(context)
    if not state or not update.message:
        return False

    lowered = text.strip().lower()
    draft = _get_broadcast_draft(context)
    skip_values = {"пропустить", "нет", "skip"}

    if state == "photo":
        if lowered not in skip_values:
            await update.message.reply_text(
                "Сейчас ожидаю фото. Пришлите изображение или напишите `пропустить`."
            )
            return True
        draft["photo_file_id"] = None
        _set_broadcast_state(context, "text")
        await update.message.reply_text("Шаг 2/5. Напишите текст рассылки.")
        return True

    if state == "text":
        if not text:
            await update.message.reply_text("Текст пустой. Напишите текст рассылки.")
            return True
        draft["text"] = text
        _set_broadcast_state(context, "buttons_choice")
        await update.message.reply_text("Шаг 3/5. Нужны кнопки? Ответьте `да` или `нет`.")
        return True

    if state == "buttons_choice":
        if lowered in {"да", "yes", "y"}:
            _set_broadcast_state(context, "buttons")
            await update.message.reply_text(
                "Пришлите кнопки, каждая с новой строки в формате:\n"
                "Текст кнопки | https://example.com\n"
                "Если кнопки не нужны, напишите `пропустить`."
            )
            return True
        if lowered in {"нет", "no", "n"}:
            draft["buttons"] = []
            _set_broadcast_state(context, "recipients")
            await update.message.reply_text(_broadcast_recipients_prompt())
            return True
        await update.message.reply_text("Ответьте `да` или `нет`.")
        return True

    if state == "buttons":
        if lowered in skip_values:
            draft["buttons"] = []
            _set_broadcast_state(context, "recipients")
            await update.message.reply_text(_broadcast_recipients_prompt())
            return True

        buttons, error = _parse_broadcast_buttons(text)
        if error:
            await update.message.reply_text(error)
            return True
        draft["buttons"] = buttons
        _set_broadcast_state(context, "recipients")
        await update.message.reply_text(_broadcast_recipients_prompt())
        return True

    if state == "recipients":
        store: SQLiteStateStore = context.application.bot_data["store"]
        if lowered in {"all", "все", "база"}:
            usernames = store.list_client_usernames()
        else:
            usernames = _parse_broadcast_usernames(text)

        if not usernames:
            await update.message.reply_text(
                "Не нашел получателей. Введите `all` или список username."
            )
            return True

        draft["usernames"] = usernames
        _set_broadcast_state(context, "confirm")
        await update.message.reply_text(
            "\n".join(
                [
                    "Шаг 5/5. Проверьте рассылку:",
                    f"Фото: {'да' if draft.get('photo_file_id') else 'нет'}",
                    f"Кнопок: {len(draft.get('buttons', []))}",
                    f"Получателей: {len(usernames)}",
                    "Ниже отправляю предпросмотр. Напишите `отправить` или `отмена`.",
                ]
            )
        )
        await _send_custom_broadcast_payload(
            context.bot,
            update.effective_chat.id,
            draft,
        )
        return True

    if state == "confirm":
        if lowered in {"отмена", "cancel", "нет"}:
            _clear_broadcast_flow(context)
            await update.message.reply_text("Кастомная рассылка отменена.")
            return True
        if lowered in {"отправить", "send", "старт"}:
            await _run_custom_broadcast(update, context, draft)
            _clear_broadcast_flow(context)
            return True
        await update.message.reply_text("Напишите `отправить` для запуска или `отмена`.")
        return True

    return False


def _broadcast_recipients_prompt() -> str:
    return (
        "Шаг 4/5. Укажите базу получателей:\n"
        "- `all` чтобы отправить всем клиентам из базы.\n"
        "- или список username через пробел, запятую или с новой строки."
    )


def _parse_broadcast_usernames(text: str) -> list[str]:
    raw_tokens = [
        token.strip()
        for chunk in text.replace(",", " ").replace(";", " ").splitlines()
        for token in chunk.split()
    ]
    seen: set[str] = set()
    usernames: list[str] = []
    for raw in raw_tokens:
        normalized = _normalize_broadcast_target(raw)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        usernames.append(normalized)
    return usernames


def _normalize_broadcast_target(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""
    if cleaned.startswith("id:"):
        suffix = cleaned[3:].strip()
        return f"id:{suffix}" if suffix.isdigit() else ""
    if cleaned.isdigit():
        return cleaned
    if not cleaned.startswith("@"):
        cleaned = f"@{cleaned}"
    return cleaned.lower()


def _parse_broadcast_buttons(text: str) -> tuple[list[tuple[str, str]], str | None]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return [], "Список кнопок пустой. Пришлите строки в формате: Текст | https://url"
    if len(lines) > 10:
        return [], "Слишком много кнопок. Максимум 10."

    buttons: list[tuple[str, str]] = []
    for index, line in enumerate(lines, start=1):
        if "|" not in line:
            return [], f"Строка {index}: нет разделителя `|`."
        label, url = [part.strip() for part in line.split("|", maxsplit=1)]
        if not label:
            return [], f"Строка {index}: пустой текст кнопки."
        if not _is_valid_button_url(url):
            return [], f"Строка {index}: некорректная ссылка."
        buttons.append((label, url))
    return buttons, None


def _is_valid_button_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _build_broadcast_keyboard(buttons: list[tuple[str, str]]):
    if not buttons:
        return None
    rows = [[InlineKeyboardButton(label, url=url)] for label, url in buttons]
    return InlineKeyboardMarkup(rows)


def _resolve_broadcast_target(store: SQLiteStateStore, username: str):
    chat_id = store.get_chat_id(username)
    if chat_id:
        return chat_id
    if username.startswith("id:") and username[3:].isdigit():
        return int(username[3:])
    if username.isdigit():
        return int(username)
    return username if username.startswith("@") else f"@{username}"


async def _send_custom_broadcast_payload(bot, target, draft: dict) -> None:
    text = str(draft.get("text", "")).strip()
    if not text:
        return
    buttons = draft.get("buttons", [])
    keyboard = _build_broadcast_keyboard(buttons)
    photo_file_id = draft.get("photo_file_id")
    if photo_file_id:
        if len(text) <= 1024:
            await bot.send_photo(
                chat_id=target,
                photo=photo_file_id,
                caption=text,
                reply_markup=keyboard,
            )
            return
        await bot.send_photo(chat_id=target, photo=photo_file_id)
        await bot.send_message(chat_id=target, text=text, reply_markup=keyboard)
        return
    await bot.send_message(chat_id=target, text=text, reply_markup=keyboard)


async def _run_custom_broadcast(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    draft: dict,
) -> None:
    if not update.message or not update.effective_chat:
        return
    usernames = list(draft.get("usernames", []))
    if not usernames:
        await update.message.reply_text("Список получателей пустой, рассылка отменена.")
        return

    await update.message.reply_text(f"Запускаю рассылку. Получателей: {len(usernames)}")
    store: SQLiteStateStore = context.application.bot_data["store"]
    sent = 0
    failed = 0
    failed_lines: list[str] = []
    for username in usernames:
        target = _resolve_broadcast_target(store, username)
        try:
            await _send_custom_broadcast_payload(context.bot, target, draft)
            sent += 1
        except TelegramError as exc:
            failed += 1
            if len(failed_lines) < 10:
                failed_lines.append(f"{username}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            if len(failed_lines) < 10:
                failed_lines.append(f"{username}: {type(exc).__name__}")

    lines = [
        "Кастомная рассылка завершена.",
        f"Успешно: {sent}",
        f"Ошибок: {failed}",
    ]
    if failed_lines:
        lines.append("Первые ошибки:")
        lines.extend(failed_lines)
    await update.effective_chat.send_message("\n".join(lines))


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
