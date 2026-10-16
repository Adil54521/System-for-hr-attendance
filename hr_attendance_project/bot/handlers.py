import asyncio
import logging
import os
import socket
import sys
import time
import uuid

import aiohttp


# =========================================================
# DJANGO
# =========================================================

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

sys.path.insert(0, BASE_DIR)

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "hr_attendance_project.settings"
)

import django

django.setup()


# =========================================================
# IMPORTS
# =========================================================

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from asgiref.sync import sync_to_async
from django.utils import timezone

from myapp.models import MessageHistory, Teacher
from myapp.utilis import normalize_phone
from myapp.utils.attendance_signing import (
    sign_attendance_payload,
)


# =========================================================
# SETTINGS
# =========================================================

router = Router()

logger = logging.getLogger("attendance")

INSTANCE_ID = (
    os.getenv("BOT_INSTANCE_ID")
    or (
        f"{socket.gethostname()}-"
        f"{os.getpid()}-"
        f"{uuid.uuid4().hex[:8]}"
    )
)

DJANGO_ATTENDANCE_URL = os.getenv(
    "ATTENDANCE_API_URL",
    "https://hrattendance.kuam.kz/webapp/"
)


# =========================================================
# KEYBOARDS
# =========================================================

location_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(
                text="📍 Отправить геолокацию",
                request_location=True
            )
        ]
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
)


def _contact_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text=(
                        "📱 НАЖАТЬ КНОПКУ "
                        "ОТПРАВИТЬ НОМЕР ТЕЛЕФОНА"
                    ),
                    request_contact=True
                )
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


# =========================================================
# DATABASE FUNCTIONS
# =========================================================

@sync_to_async
def get_teacher_by_telegram_id(telegram_id):
    return (
        Teacher.objects
        .filter(telegram_id=telegram_id)
        .first()
    )


@sync_to_async
def update_teacher_telegram_id(
    phone,
    telegram_id
):
    return (
        Teacher.objects
        .filter(phone_clean=phone)
        .update(telegram_id=telegram_id)
    )


@sync_to_async
def get_pending_confirmation_messages(
    telegram_id: int
) -> list[int]:
    """
    Получаем Telegram message_id всех сообщений,
    которые пользователь ещё не подтвердил.
    """

    return list(
        MessageHistory.objects
        .filter(
            recipient__telegram_id=telegram_id,
            read_at__isnull=True,
            telegram_message_id__isnull=False
        )
        .values_list(
            "telegram_message_id",
            flat=True
        )
    )


@sync_to_async
def mark_message_as_read(
    history_id: int,
    telegram_user_id: int
) -> str:
    """
    Сохраняет подтверждение прочтения сообщения.
    """

    history_item = (
        MessageHistory.objects
        .select_related("recipient")
        .filter(pk=history_id)
        .first()
    )

    if history_item is None:
        return "not_found"

    recipient_telegram_id = (
        history_item.recipient.telegram_id
    )

    # Проверяем, что кнопку нажал именно тот
    # пользователь, которому отправлялось сообщение
    if str(recipient_telegram_id) != str(
        telegram_user_id
    ):
        return "forbidden"

    if history_item.read_at is not None:
        return "already_read"

    history_item.read_at = timezone.now()

    history_item.save(
        update_fields=["read_at"]
    )

    return "success"


# =========================================================
# CONFIRMATION BUTTONS
# =========================================================

async def remove_confirmation_buttons(
    message: Message
) -> None:
    """
    Удаляет inline-кнопки подтверждения из старых
    непрочитанных сообщений пользователя.

    При этом сообщения не отмечаются прочитанными.
    """

    telegram_message_ids = (
        await get_pending_confirmation_messages(
            telegram_id=message.from_user.id
        )
    )

    for telegram_message_id in telegram_message_ids:
        try:
            await message.bot.edit_message_reply_markup(
                chat_id=message.chat.id,
                message_id=telegram_message_id,
                reply_markup=None
            )

        except TelegramBadRequest as error:
            logger.warning(
                "confirmation_button_remove_failed",
                extra={
                    "event": (
                        "confirmation_button_remove_failed"
                    ),
                    "telegram_user_id": (
                        message.from_user.id
                    ),
                    "telegram_message_id": (
                        telegram_message_id
                    ),
                    "reason": str(error),
                }
            )


@router.callback_query(
    F.data.startswith("message_read:")
)
async def confirm_message_read(
    callback: CallbackQuery
):
    """
    Обрабатывает кнопку «Прочитал».
    """

    try:
        history_id = int(
            callback.data.split(":", 1)[1]
        )

    except (
        ValueError,
        IndexError,
        AttributeError
    ):
        await callback.answer(
            "Некорректная кнопка",
            show_alert=True
        )
        return

    result = await mark_message_as_read(
        history_id=history_id,
        telegram_user_id=callback.from_user.id
    )

    if result == "not_found":
        await callback.answer(
            "Сообщение не найдено",
            show_alert=True
        )
        return

    if result == "forbidden":
        await callback.answer(
            (
                "Это сообщение предназначено "
                "другому пользователю"
            ),
            show_alert=True
        )
        return

    if result == "already_read":
        await callback.answer(
            "Вы уже подтвердили прочтение"
        )

        # Если кнопка почему-то осталась,
        # удаляем её
        if callback.message:
            try:
                await callback.message.edit_reply_markup(
                    reply_markup=None
                )
            except TelegramBadRequest:
                pass

        return

    await callback.answer(
        "Прочтение подтверждено"
    )

    # После успешного подтверждения удаляем кнопку
    if callback.message:
        try:
            await callback.message.edit_reply_markup(
                reply_markup=None
            )
        except TelegramBadRequest as error:
            logger.warning(
                "confirmation_button_edit_failed",
                extra={
                    "event": (
                        "confirmation_button_edit_failed"
                    ),
                    "telegram_user_id": (
                        callback.from_user.id
                    ),
                    "history_id": history_id,
                    "reason": str(error),
                }
            )

        await callback.message.answer(
            "✅ Вы подтвердили, что прочитали сообщение."
        )


# =========================================================
# LOGGING HELPERS
# =========================================================

def _event_fields(
    message: Message,
    event_update: Update,
    data: dict
) -> dict:
    return {
        "update_id": event_update.update_id,
        "message_id": message.message_id,
        "chat_id": message.chat.id,
        "telegram_user_id": message.from_user.id,
        "action_id": data.get("action_id", ""),
        "correlation_id": data.get(
            "correlation_id",
            ""
        ),
        "instance_id": INSTANCE_ID,
        "process_id": os.getpid(),
        "handler_name": (
            "handle_location"
            if message.location
            else "handle_contact"
        ),
    }


# =========================================================
# DJANGO ATTENDANCE REQUEST
# =========================================================

async def _send_attendance(
    payload: dict,
    fields: dict
) -> tuple[int, dict]:
    started = time.perf_counter()

    logger.info(
        "django_request_started",
        extra={
            **fields,
            "event": "django_request_started"
        }
    )

    try:
        timeout = aiohttp.ClientTimeout(
            total=10.0,
            connect=5.0
        )

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as client:
            async with client.post(
                DJANGO_ATTENDANCE_URL,
                json=payload,
                headers={
                    "X-Attendance-Signature": (
                        sign_attendance_payload(payload)
                    )
                },
                allow_redirects=False,
            ) as response:
                try:
                    body = await response.json(
                        content_type=None
                    )

                except (
                    ValueError,
                    aiohttp.ContentTypeError
                ) as error:
                    raise RuntimeError(
                        "Сервер вернул некорректный JSON"
                    ) from error

                status_code = response.status

        logger.info(
            "django_request_finished",
            extra={
                **fields,
                "event": "django_request_finished",
                "http_status": status_code,
                "result": body.get(
                    "result",
                    "error"
                ),
                "visit_id": body.get("visit_id"),
                "duplicate_reason": body.get(
                    "duplicate_reason",
                    ""
                ),
                "duration_ms": round(
                    (
                        time.perf_counter()
                        - started
                    ) * 1000,
                    2
                ),
            }
        )

        return status_code, body

    except (
        asyncio.TimeoutError,
        aiohttp.ClientError
    ) as error:
        logger.warning(
            "attendance_operation_failed",
            extra={
                **fields,
                "event": (
                    "attendance_operation_failed"
                ),
                "reason": (
                    error.__class__.__name__
                ),
                "duration_ms": round(
                    (
                        time.perf_counter()
                        - started
                    ) * 1000,
                    2
                ),
            }
        )

        raise


async def _reply_with_result(
    message: Message,
    status_code: int,
    result: dict
) -> bool:
    if status_code != 200:
        if result.get("code") == "OUTSIDE_CAMPUS":
            text = (
                "🚫 Вы находитесь вне "
                "территории кампуса"
            )
        else:
            text = (
                f"❌ "
                f"{result.get('error', 'Ошибка сервера')}"
            )

        await message.answer(
            text,
            reply_markup=ReplyKeyboardRemove()
        )

        return False

    status = result.get("status", "")

    if "ВЫ ВОШЛИ" in status:
        text = f"🟢 {status}"

    elif "ВЫ ВЫШЛИ" in status:
        text = f"🔴 {status}"

    else:
        text = f"⚠️ {status}"

    await message.answer(
        text,
        reply_markup=ReplyKeyboardRemove()
    )

    return True


# =========================================================
# /START
# =========================================================

@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext
):
    # При запуске основной логики удаляем
    # inline-кнопки подтверждения
    await remove_confirmation_buttons(message)

    parts = (
        message.text or ""
    ).split(" ", 1)

    await state.clear()

    await state.update_data(
        location=None,
        qr_id=(
            parts[1]
            if len(parts) > 1
            else None
        ),
        action_id=str(uuid.uuid4()),
        correlation_id=str(uuid.uuid4()),
        action_owner=message.from_user.id,
    )

    geo_keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="Отправить геолокацию",
                    request_location=True
                )
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

    await message.answer(
        (
            "НАЖМИТЕ КНОПКУ ДЛЯ ОТПРАВКИ "
            "ГЕОЛОКАЦИИ ДЛЯ ОТМЕТКИ!"
        ),
        reply_markup=geo_keyboard,
    )


# =========================================================
# CONTACT
# =========================================================

@router.message(F.contact)
async def handle_contact(
    message: Message,
    state: FSMContext,
    event_update: Update
):
    if (
        not message.contact
        or (
            message.contact.user_id
            != message.from_user.id
        )
    ):
        await message.answer(
            (
                "❌ Вы не можете отправить "
                "чужой номер телефона."
            )
        )
        return

    data = await state.get_data()

    if (
        not data.get("action_id")
        or (
            data.get("action_owner")
            != message.from_user.id
        )
    ):
        await message.answer(
            (
                "❌ Сеанс регистрации истёк. "
                "Отправьте /start и повторите действие."
            ),
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    phone = normalize_phone(
        message.contact.phone_number
    )

    updated = await update_teacher_telegram_id(
        phone=phone,
        telegram_id=message.from_user.id
    )

    if updated == 0:
        await message.answer(
            (
                "❌ Преподаватель с таким "
                "номером не найден."
            )
        )
        return

    await state.update_data(phone=phone)

    data = await state.get_data()

    if (
        data.get("latitude") is None
        or data.get("longitude") is None
    ):
        await message.answer(
            "📍 Сначала отправьте геолокацию",
            reply_markup=location_keyboard
        )
        return

    fields = _event_fields(
        message,
        event_update,
        data
    )

    try:
        status_code, result = (
            await _send_attendance(
                _build_payload(
                    data,
                    message.from_user.id,
                    phone
                ),
                fields
            )
        )

    except (
        aiohttp.ClientError,
        asyncio.TimeoutError,
        RuntimeError
    ):
        await message.answer(
            (
                "❌ Сервер временно недоступен. "
                "Повторите отправку контакта."
            )
        )
        return

    if await _reply_with_result(
        message,
        status_code,
        result
    ):
        await state.clear()


# =========================================================
# LOCATION
# =========================================================

@router.message(F.location)
async def handle_location(
    message: Message,
    state: FSMContext,
    event_update: Update
):
    # Перед обработкой геолокации повторно
    # убираем кнопки подтверждения
    await remove_confirmation_buttons(message)

    started = time.perf_counter()

    data = await state.get_data()

    fields = _event_fields(
        message,
        event_update,
        data
    )

    logger.info(
        "telegram_update_received",
        extra={
            **fields,
            "event": "telegram_update_received"
        }
    )

    logger.info(
        "location_handler_started",
        extra={
            **fields,
            "event": "location_handler_started"
        }
    )

    if (
        not data.get("action_id")
        or (
            data.get("action_owner")
            != message.from_user.id
        )
    ):
        logger.warning(
            "attendance_operation_failed",
            extra={
                **fields,
                "event": (
                    "attendance_operation_failed"
                ),
                "reason": (
                    "missing_or_foreign_fsm_action"
                ),
            }
        )

        await message.answer(
            (
                "❌ Сеанс регистрации истёк. "
                "Отправьте /start и повторите действие."
            ),
            reply_markup=ReplyKeyboardRemove(),
        )

        return

    latitude = message.location.latitude
    longitude = message.location.longitude
    accuracy = (
        message.location.horizontal_accuracy
        or 0
    )

    if accuracy > 100:
        await message.answer(
            (
                "⚠️ Геолокация слишком неточная "
                "(>100м). Повторите на улице."
            )
        )
        return

    await state.update_data(
        latitude=latitude,
        longitude=longitude,
        accuracy=accuracy,
        update_id=event_update.update_id,
        message_id=message.message_id,
        chat_id=message.chat.id,
    )

    data = await state.get_data()

    teacher = await get_teacher_by_telegram_id(
        message.from_user.id
    )

    phone = data.get("phone")

    if not teacher or not teacher.telegram_id:
        if not phone:
            await message.answer(
                (
                    "📱 СНАЧАЛА НАЖМИТЕ КНОПКУ "
                    "ОТПРАВИТЬ НОМЕР ТЕЛЕФОНА !"
                ),
                reply_markup=_contact_keyboard(),
            )

            return
    else:
        phone = teacher.phone_clean

    try:
        status_code, result = (
            await _send_attendance(
                _build_payload(
                    data,
                    message.from_user.id,
                    phone
                ),
                fields
            )
        )

    except (
        aiohttp.ClientError,
        asyncio.TimeoutError,
        RuntimeError
    ):
        await message.answer(
            (
                "❌ Сервер временно недоступен. "
                "Повторите отправку геолокации — "
                "действие не изменится дважды."
            )
        )

        return

    if await _reply_with_result(
        message,
        status_code,
        result
    ):
        await state.clear()

    # После обработки гарантированно повторяем очистку
    await remove_confirmation_buttons(message)

    logger.info(
        "location_handler_finished",
        extra={
            **fields,
            "event": (
                "location_handler_finished"
            ),
            "duration_ms": round(
                (
                    time.perf_counter()
                    - started
                ) * 1000,
                2
            ),
            "result": result.get(
                "result",
                "error"
            ),
            "visit_id": result.get(
                "visit_id"
            ),
        }
    )


# =========================================================
# PAYLOAD
# =========================================================

def _build_payload(
    data: dict,
    telegram_user_id: int,
    phone: str | None
) -> dict:
    return {
        "source": "telegram_bot",
        "action_id": data["action_id"],
        "correlation_id": data.get(
            "correlation_id",
            ""
        ),
        "instance_id": INSTANCE_ID,
        "phone": phone,
        "qr_id": data.get("qr_id"),
        "telegram_id": telegram_user_id,
        "telegram_user_id": telegram_user_id,
        "update_id": data.get("update_id"),
        "message_id": data.get("message_id"),
        "chat_id": data.get("chat_id"),
        "latitude": data.get("latitude"),
        "longitude": data.get("longitude"),
        "accuracy": data.get("accuracy"),
    }