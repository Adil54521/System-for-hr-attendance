# bot/keyboards.py

from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo
)

# Клавиатура для запроса номера телефона
contact_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📲 Отправить данные", request_contact=True)]
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)

# Клавиатура для запроса геолокации (обычная)
geo_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Отправить геолокацию", request_location=True)]
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)

# Кнопка WebApp для безопасной геопроверки
def get_webapp_keyboard(phone: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="Проверка геолокации (WebApp)",
            web_app=WebAppInfo(url=f"https://hrattendance.kuam.kz/webapp/?phone={phone}")
        )
    ]])


# При необходимости можно добавить ещё клавиатуры (меню, подтверждение, отмена и т.д.)
