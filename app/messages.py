from urllib.parse import quote

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

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

CONTACT_TEXT = "Здравствуйте! Я перешел от телеграмм-бота."
CONTACT_URL = f"https://t.me/GoldenDentNSK?text={quote(CONTACT_TEXT)}"


def build_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("1) Записаться сейчас", url=CONTACT_URL)],
            [InlineKeyboardButton("2) Напомните через 2 недели", callback_data="remind_2w")],
            [InlineKeyboardButton("3) Не готов записаться", callback_data="not_ready")],
        ]
    )


async def send_main_message(bot, chat_id: int) -> None:
    await bot.send_message(chat_id=chat_id, text=MAIN_MESSAGE, reply_markup=build_main_keyboard())


async def send_start_message(bot, chat_id: int) -> None:
    await bot.send_message(chat_id=chat_id, text=START_MESSAGE, reply_markup=build_main_keyboard())