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
    "Клиника «Голден Дент», рады видеть в числе наших пациентов."
)

ABOUT_TEXT = (
    "«ГОЛДЕН ДЕНТ» - БЕСЦЕННАЯ ИНВЕСТИЦИЯ В ВАШЕ ЗДОРОВЬЕ!\n"
    "На протяжении 20 лет мы предоставляем нашим пациентам современную и эффективную "
    "стоматологическую помощь.\n"
    "Безупречная репутация, высокий уровень качества стоматологических услуг, "
    "индивидуальный и комплексный подход к каждому пациенту - наш приоритет!"
)

SPECIAL_OFFERS_TEXT = "Скоро обновим информацию.."

_ADMIN_USERNAME = "GoldenDentNSK"
_LOGO_PATH = Path(__file__).resolve().parent.parent / "logo-gd.jpg"

CONTACT_TEXT = "Здравствуйте! Я перешел от телеграмм-бота."
CONTACT_URL = f"https://t.me/{_ADMIN_USERNAME}?text={quote(CONTACT_TEXT)}"

BOOK_APPOINTMENT_TEXT = "Здравствуйте! Я хочу записаться на прием"
BOOK_APPOINTMENT_URL = f"https://t.me/{_ADMIN_USERNAME}?text={quote(BOOK_APPOINTMENT_TEXT)}"
CONTACT_ADMIN_URL = f"https://t.me/{_ADMIN_USERNAME}"


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
