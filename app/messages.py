from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

logger = logging.getLogger("golden-dent")

_MAIN_MESSAGE_TEMPLATE = (
    "Здравствуйте!\n\n"
    "Вас приветствует клиника «Голден Дент».\n\n"
    "С момента вашего последнего визита прошло {months} месяцев — это оптимальное время "
    "для профилактического осмотра и профессиональной гигиены.\n\n"
    "Будем рады видеть вас!"
)
MAIN_MESSAGE = _MAIN_MESSAGE_TEMPLATE.format(months=6)

START_MESSAGE = (
    "Здравствуйте! Вас приветствует клиника Голден Дент!\n\n"
    "Готовы записаться?)"
)

INFO_START_MESSAGE = (
    "Здравствуйте!\n"
    "Клиника «Голден Дент», рады видеть вас в числе наших пациентов."
)

CONSENT_MESSAGE = (
    "Добро пожаловать в чат-бот клиники.\n\n"
    "Для продолжения нажмите «Продолжить».\n\n"
    "Нажимая кнопку, вы даёте согласие на обработку ваших персональных данных "
    "(ФИО, номер телефона, дата рождения) для:\n"
    "• ведения базы пациентов\n"
    "• связи с вами\n"
    "• отправки сервисных сообщений, включая поздравления и подарки в день рождения."
)

CONSENT_POLICY_TEXT = (
    "Политика обработки персональных данных не настроена в боте. "
    "Добавьте ссылку на опубликованный документ в настройках окружения."
)

CONSENT_RULES_TEXT = (
    "Правила использования чат-бота не настроены в боте. "
    "Добавьте ссылку на опубликованный документ в настройках окружения."
)

ABOUT_TEXT = (
    "«ГОЛДЕН ДЕНТ» - БЕСЦЕННАЯ ИНВЕСТИЦИЯ В ВАШЕ ЗДОРОВЬЕ!\n"
    "На протяжении 20 лет мы предоставляем нашим пациентам современную и эффективную "
    "стоматологическую помощь.\n"
    "Безупречная репутация, высокий уровень качества стоматологических услуг, "
    "индивидуальный и комплексный подход к каждому пациенту - наш приоритет!"
)

SPECIAL_OFFERS_HEADER = "МЫ ДЕЛАЕМ ПРЕМИАЛЬНУЮ СТОМАТОЛОГИЮ ДОСТУПНОЙ"

ADULT_SUBSCRIPTION_TEXT = (
    "🔘ВЗРОСЛЫЙ АБОНЕМЕНТ НА 4 ПРОФЕССИОНАЛЬНЫХ ЧИСТКИ ЗУБОВ - 18 000 ₽\n\n"
    "Абонемент на 4 чистки, срок действия - 2 года! Абонемент не именной, "
    "им могут воспользоваться ваши родственники и друзья.\n\n"
    "🔘В спецпредложение входит:\n"
    "✔️ Осмотр и консультация стоматолога\n"
    "✔️ Фотопротокол полости рта (при необходимости)\n"
    "✔️ Удаление зубного камня ультразвуком\n"
    "✔️ Пескоструйный аппарат Air Flow\n"
    "✔️ Полировка зубов профессиональной пастой и щеткой\n"
    "✔️ Фторирование\n"
    "✔️ Подбор и рекомендации по использованию средств личной гигиены полости рта.\n\n"
    "📍Данный абонемент действует при предъявлении.\n"
    "*Абонемент распространяется не на всех специалистов"
)

CHILD_SUBSCRIPTION_TEXT = (
    "🔘ДЕТСКИЙ АБОНЕМЕНТ НА 4 ПРОФЕССИОНАЛЬНЫХ ЧИСТКИ ЗУБОВ - 14 000 ₽\n\n"
    "🔘Абонемент на 4 чистки, срок действия - 1 год! Абонемент не именной, "
    "им могут воспользоваться ваши родственники и друзья до 14 лет.\n\n"
    "🔘В спецпредложение входит:\n"
    "✔️ Осмотр и консультация стоматолога\n"
    "✔️ Беседа с родителями\n"
    "✔️ Фотопротокол полости рта (при необходимости)\n"
    "✔️ Удаление зубного камня ультразвуком\n"
    "✔️ Пескоструйный аппарат Air Flow\n"
    "✔️ Полировка зубов профессиональной пастой и щеткой\n"
    "✔️ Фторирование\n"
    "✔️ Подбор и рекомендации по использованию средств личной гигиены полости рта.\n\n"
    "📍Данный абонемент действует при предъявлении.\n"
    "*Абонемент распространяется не на всех специалистов"
)

IMPLANT_CROWN_TEXT = (
    "🔘ИМПЛАНТАЦИЯ + ЦИРКОНИЕВАЯ КОРОНКА «под ключ» - 59 000 ₽\n\n"
    "В спецпредложение входит:\n"
    "✔️ осмотр и консультация стоматолога - хирурга\n"
    "✔️ анестезия\n"
    "✔️ установка импланта системы \"Osstem\"\n"
    "✔️ контрольная рентгенография (2 шт.)\n"
    "✔️ стоматологические оттиски\n"
    "✔️ абатмент на имплант\n"
    "✔️ формирователь десны\n"
    "✔️ изготовление и фиксация циркониевой коронки\n\n"
    "📍Спецпредложение действует при единоразовой оплате.\n\n"
    "*Есть противопоказания, необходима консультация специалиста. "
    "Вы можете уточнить условия акции у администраторов GD."
)

ULTRASOUND_EXTRACTION_TEXT = (
    "🔘 СОВРЕМЕННАЯ УЛЬТРАЗВУКОВАЯ ХИРУРГИЯ.\n"
    "УДАЛЕНИЕ ЗУБОВ. - 9 900 ₽\n\n"
    "🔘В спецпредложение входит:\n"
    "✔️осмотр и консультация стоматолога - хирурга\n"
    "✔️анестезия\n"
    "✔️удаление зуба с помощью Пьезо (ультразвука)\n"
    "✔️антисептическая обработка\n"
    "✔️наложение швов\n\n"
    "Без боли и страха - максимальный комфорт!\n\n"
    "*Есть противопоказания, необходима консультация специалиста. "
    "Вы можете уточнить условия акции у администраторов GD."
)

FLASH_WHITENING_TEXT = (
    "🔘НЕМЕЦКОЕ ПРОФЕССИОНАЛЬНОЕ ОТБЕЛИВАНИЕ \"FLASH\"- 29900\n\n"
    "🔘В спецпредложение входит:\n"
    "✔️осмотр и консультация стоматолога - терапевта\n"
    "✔️фотопротокол\n"
    "✔️отбеливание премиальной системой \"Flash\"\n"
    "✔️покрытие реминерализирующим препаратом\n\n"
    "Улыбнись белоснежной улыбкой!\n\n"
    "*Есть противопоказания, необходима консультация специалиста. "
    "Вы можете уточнить условия акции у администраторов GD."
)

_ADMIN_USERNAME = "GoldenDentNSK"
_LOGO_PATH = Path(__file__).resolve().parent.parent / "logo-gd.jpg"
_SPECIAL_SUG_PATH = Path(__file__).resolve().parent.parent / "special-sug.jpg"
_ABOUT_PHOTO_PATH = Path(__file__).resolve().parent.parent / "ew-photo.jpg"
_SUBSCRIPTION_URL = "https://голдендент.рф/оплата-абонемента"

CONTACT_TEXT = "Здравствуйте! Я перешел от телеграмм-бота."
CONTACT_URL = f"https://t.me/{_ADMIN_USERNAME}?text={quote(CONTACT_TEXT)}"

BOOK_APPOINTMENT_TEXT = "Здравствуйте! Я хочу записаться на прием"
BOOK_APPOINTMENT_URL = f"https://t.me/{_ADMIN_USERNAME}?text={quote(BOOK_APPOINTMENT_TEXT)}"
CONTACT_ADMIN_URL = f"https://t.me/{_ADMIN_USERNAME}"

IMPLANT_CONTACT_TEXT = (
    "Здравствуйте! Меня заинтересовала услуга "
    "\"Имплантация + циркониевая коронка под ключ\""
)
ULTRASOUND_CONTACT_TEXT = (
    "Здравствуйте! Меня заинтересовала услуга "
    "\"Современная ультразвуковая хирургия. Удаление зубов\""
)
FLASH_CONTACT_TEXT = (
    "Здравствуйте! Меня заинтересовала услуга "
    "\"Немецкое профессиональное отбеливание FLASH\""
)
ADULT_SUBSCRIPTION_CONTACT_TEXT = (
    "Здравствуйте! Меня заинтересовала услуга "
    "\"Взрослый абонемент на 4 профессиональных чистки зубов\""
)
CHILD_SUBSCRIPTION_CONTACT_TEXT = (
    "Здравствуйте! Меня заинтересовала услуга "
    "\"Детский абонемент на 4 профессиональных чистки зубов\""
)

IMPLANT_CONTACT_URL = f"https://t.me/{_ADMIN_USERNAME}?text={quote(IMPLANT_CONTACT_TEXT)}"
ULTRASOUND_CONTACT_URL = f"https://t.me/{_ADMIN_USERNAME}?text={quote(ULTRASOUND_CONTACT_TEXT)}"
FLASH_CONTACT_URL = f"https://t.me/{_ADMIN_USERNAME}?text={quote(FLASH_CONTACT_TEXT)}"
ADULT_SUBSCRIPTION_CONTACT_URL = (
    f"https://t.me/{_ADMIN_USERNAME}?text={quote(ADULT_SUBSCRIPTION_CONTACT_TEXT)}"
)
CHILD_SUBSCRIPTION_CONTACT_URL = (
    f"https://t.me/{_ADMIN_USERNAME}?text={quote(CHILD_SUBSCRIPTION_CONTACT_TEXT)}"
)


BIRTHDAY_CONTACT_TEXT = "Здравствуйте! Хочу использовать подарочный сертификат ко дню рождения."
BIRTHDAY_USE_BONUSES_URL = f"https://t.me/{_ADMIN_USERNAME}?text={quote(BIRTHDAY_CONTACT_TEXT)}"


def build_consent_keyboard(
    policy_url: str | None = None,
    rules_url: str | None = None,
) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("✔ Продолжить", callback_data="consent_accept")]]
    if policy_url:
        rows.append([InlineKeyboardButton("Политика обработки персональных данных", url=policy_url)])
    else:
        rows.append(
            [InlineKeyboardButton("Политика обработки персональных данных", callback_data="consent_doc:policy")]
        )
    if rules_url:
        rows.append([InlineKeyboardButton("Правила использования чат-бота", url=rules_url)])
    else:
        rows.append(
            [InlineKeyboardButton("Правила использования чат-бота", callback_data="consent_doc:rules")]
        )
    return InlineKeyboardMarkup(rows)


def build_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("1) Записаться сейчас", url=CONTACT_URL)],
            [InlineKeyboardButton("2) Напомните через 2 недели", callback_data="remind_2w")],
            [InlineKeyboardButton("3) Не готов записаться", callback_data="not_ready")],
        ]
    )


def build_info_start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Записаться на прием", url=BOOK_APPOINTMENT_URL)],
            [InlineKeyboardButton("О нас", callback_data="about_us")],
            [InlineKeyboardButton("Спец предложения", callback_data="special_offers")],
            [InlineKeyboardButton("Связаться с администратором", url=CONTACT_ADMIN_URL)],
        ]
    )


def build_special_offers_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Взрослый абонемент", callback_data="offer_adult")],
            [InlineKeyboardButton("Детский абонемент", callback_data="offer_child")],
            [InlineKeyboardButton("Имплантация + коронка", callback_data="offer_implant")],
            [InlineKeyboardButton("Удаление зубов ультразвуком", callback_data="offer_ultrasound")],
            [InlineKeyboardButton("Отбеливание \"FLASH\"", callback_data="offer_flash")],
        ]
    )


def build_adult_subscription_keyboard() -> InlineKeyboardMarkup:
    return _build_offer_actions_keyboard(ADULT_SUBSCRIPTION_CONTACT_URL)


def build_child_subscription_keyboard() -> InlineKeyboardMarkup:
    return _build_offer_actions_keyboard(CHILD_SUBSCRIPTION_CONTACT_URL)


def _build_offer_actions_keyboard(
    contact_url: str, include_buy_subscription: bool = True
) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("Записаться", url=contact_url)]]
    if include_buy_subscription:
        rows.append([InlineKeyboardButton("Купить абонемент", url=_SUBSCRIPTION_URL)])
    rows.append([InlineKeyboardButton("В начало", callback_data="go_start")])
    return InlineKeyboardMarkup(rows)


def build_implant_contact_keyboard() -> InlineKeyboardMarkup:
    return _build_offer_actions_keyboard(IMPLANT_CONTACT_URL, include_buy_subscription=False)


def build_ultrasound_contact_keyboard() -> InlineKeyboardMarkup:
    return _build_offer_actions_keyboard(ULTRASOUND_CONTACT_URL)


def build_flash_contact_keyboard() -> InlineKeyboardMarkup:
    return _build_offer_actions_keyboard(FLASH_CONTACT_URL)


def build_birthday_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🎁 Использовать сертификат", url=BIRTHDAY_USE_BONUSES_URL)]]
    )


async def send_main_message(bot, chat_id: int, reminder_months: int = 6) -> None:
    text = _MAIN_MESSAGE_TEMPLATE.format(months=reminder_months)
    await bot.send_message(chat_id=chat_id, text=text, reply_markup=build_main_keyboard())


async def send_start_message(bot, chat_id: int) -> None:
    await bot.send_message(chat_id=chat_id, text=START_MESSAGE, reply_markup=build_main_keyboard())


async def send_info_start_message(
    bot,
    chat_id: int,
    message_text: str | None = None,
    photo_file_id: str | None = None,
    keyboard: InlineKeyboardMarkup | None = None,
) -> None:
    caption = message_text if message_text is not None else INFO_START_MESSAGE
    reply_markup = keyboard if keyboard is not None else build_info_start_keyboard()
    if photo_file_id:
        try:
            await bot.send_photo(
                chat_id=chat_id,
                photo=photo_file_id,
                caption=caption,
                reply_markup=reply_markup,
            )
            return
        except TelegramError as exc:
            logger.warning("Failed to send start photo by file_id: %s", exc)

    if _LOGO_PATH.exists():
        with _LOGO_PATH.open("rb") as logo:
            await bot.send_photo(
                chat_id=chat_id,
                photo=logo,
                caption=caption,
                reply_markup=reply_markup,
            )
        return

    logger.warning("Start logo file not found: %s", _LOGO_PATH)
    await bot.send_message(
        chat_id=chat_id,
        text=caption,
        reply_markup=reply_markup,
    )


async def send_special_offers_message(
    bot,
    chat_id: int,
    header: str | None = None,
    keyboard: InlineKeyboardMarkup | None = None,
) -> None:
    message_header = header if header is not None else SPECIAL_OFFERS_HEADER
    reply_markup = keyboard if keyboard is not None else build_special_offers_keyboard()
    if _SPECIAL_SUG_PATH.exists():
        with _SPECIAL_SUG_PATH.open("rb") as image:
            await bot.send_photo(
                chat_id=chat_id,
                photo=image,
                caption=message_header,
                reply_markup=reply_markup,
            )
        return

    logger.warning("Special offers image file not found: %s", _SPECIAL_SUG_PATH)
    await bot.send_message(
        chat_id=chat_id,
        text=message_header,
        reply_markup=reply_markup,
    )


async def send_about_message(bot, chat_id: int) -> None:
    if _ABOUT_PHOTO_PATH.exists():
        with _ABOUT_PHOTO_PATH.open("rb") as image:
            await bot.send_photo(chat_id=chat_id, photo=image, caption=ABOUT_TEXT)
        return

    logger.warning("About image file not found: %s", _ABOUT_PHOTO_PATH)
    await bot.send_message(chat_id=chat_id, text=ABOUT_TEXT)


async def send_consent_message(
    bot,
    chat_id: int,
    policy_url: str | None = None,
    rules_url: str | None = None,
) -> None:
    await bot.send_message(
        chat_id=chat_id,
        text=CONSENT_MESSAGE,
        reply_markup=build_consent_keyboard(policy_url=policy_url, rules_url=rules_url),
    )


async def send_birthday_message(bot, chat_id: int, bonus_amount: int) -> None:
    await bot.send_message(
        chat_id=chat_id,
        text=(
            "Клиника «ГОЛДЕН ДЕНТ» поздравляет вас с днём рождения!\n"
            "Желаем крепкого здоровья и счастливых улыбок.\n\n"
            "В честь вашего праздника мы подготовили для вас подарок —\n"
            f"подарочный сертификат на {bonus_amount} рублей на услуги клиники.\n"
            "<i>подробности у администратора</i>\n\n"
            "Будем рады видеть вас!"
        ),
        parse_mode="HTML",
        reply_markup=build_birthday_keyboard(),
    )
