import logging
from pathlib import Path
from urllib.parse import quote

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger("golden-dent")

MAIN_MESSAGE = (
    "Здравствуйте!\n\n"
    "Вас приветствует клиника «Голден Дент».\n\n"
    "С момента вашего последнего визита прошло 6 месяцев — это оптимальное время "
    "для профилактического осмотра и профессиональной гигиены.\n\n"
    "Будем рады видеть вас!"
)

START_MESSAGE = (
    "Здравствуйте! Вас приветствует клиника Голден Дент!\n\n"
    "Готовы записаться?)"
)

INFO_START_MESSAGE = (
    "Здравствуйте!\n"
    "Клиника «Голден Дент», рады видеть вас в числе наших пациентов."
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
    "✔️глав врач ушел, нужно у него уточнить этапы…\n"
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
    "✔️глав врач ушел, нужно у него уточнить этапы…\n"
    "✔️\n"
    "✔️\n"
    "✔️\n"
    "✔️\n"
    "✔️\n\n"
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
    "\"Немецкое профессиональное отбеливание \"FLASH\"\""
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


async def send_main_message(bot, chat_id: int) -> None:
    await bot.send_message(chat_id=chat_id, text=MAIN_MESSAGE, reply_markup=build_main_keyboard())


async def send_start_message(bot, chat_id: int) -> None:
    await bot.send_message(chat_id=chat_id, text=START_MESSAGE, reply_markup=build_main_keyboard())


async def send_info_start_message(bot, chat_id: int) -> None:
    if _LOGO_PATH.exists():
        with _LOGO_PATH.open("rb") as logo:
            await bot.send_photo(
                chat_id=chat_id,
                photo=logo,
                caption=INFO_START_MESSAGE,
                reply_markup=build_info_start_keyboard(),
            )
        return

    logger.warning("Start logo file not found: %s", _LOGO_PATH)
    await bot.send_message(
        chat_id=chat_id,
        text=INFO_START_MESSAGE,
        reply_markup=build_info_start_keyboard(),
    )


async def send_special_offers_message(bot, chat_id: int) -> None:
    if _SPECIAL_SUG_PATH.exists():
        with _SPECIAL_SUG_PATH.open("rb") as image:
            await bot.send_photo(
                chat_id=chat_id,
                photo=image,
                caption=SPECIAL_OFFERS_HEADER,
                reply_markup=build_special_offers_keyboard(),
            )
        return

    logger.warning("Special offers image file not found: %s", _SPECIAL_SUG_PATH)
    await bot.send_message(
        chat_id=chat_id,
        text=SPECIAL_OFFERS_HEADER,
        reply_markup=build_special_offers_keyboard(),
    )


async def send_about_message(bot, chat_id: int) -> None:
    if _ABOUT_PHOTO_PATH.exists():
        with _ABOUT_PHOTO_PATH.open("rb") as image:
            await bot.send_photo(chat_id=chat_id, photo=image, caption=ABOUT_TEXT)
        return

    logger.warning("About image file not found: %s", _ABOUT_PHOTO_PATH)
    await bot.send_message(chat_id=chat_id, text=ABOUT_TEXT)
