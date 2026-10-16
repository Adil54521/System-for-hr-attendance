from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from myapp.models import Teacher, VisitLog, WebAppAccessLog, SuspiciousAccessLog, Campus, MessageHistory
from myapp.models import AttendanceAction
from myapp.services.attendance import (
    AttendanceConflict,
    AttendanceTemporarilyUnavailable,
    apply_attendance_action,
)
from django.contrib.admin.views.decorators import staff_member_required
from myapp.utils.attendance_signing import verify_attendance_signature
from django.utils import timezone
import qrcode
from io import BytesIO
import base64
from django.shortcuts import render, redirect
from django.http import HttpResponse
import json
from myapp.utilis import normalize_phone
from datetime import datetime, date
import math
import traceback
import requests
import logging
import uuid
from bot.config import RECEIVE_URL, BOT_TOKEN
import json
from django.shortcuts import get_object_or_404
logger = logging.getLogger("attendance")

ALLOWED_IPS = ["193.193.226.139", "127.0.0.1"]
ALLOWED_IP_PREFIXES = ["192.168.88.", "10.10.", "193.193.226."]

SUSPICIOUS_PATTERNS = [
    "x86", "emulator", "genymotion", "test-keys",
    "vbox", "build/qemu", "virtual", "debug", "root"
]
EXEMPT_PHONES = {"77711149912", "87769925552"}

# Функция для вычисления расстояния между двумя точками по формуле Хаверсина
def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371000  # Радиус Земли в метрах
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c  # Возвращаем расстояние в метрах
    
def is_suspicious_useragent(user_agent: str) -> bool:
    ua = user_agent.lower()

    for pattern in SUSPICIOUS_PATTERNS:
        if pattern in ua:
            logger.warning(f"❌ Подозрительный агент: содержит '{pattern}'")
            return True

    return False
    
#def is_ip_allowed(ip: str) -> bool:
#    allowed = ip in ALLOWED_IPS or any(ip.startswith(prefix) for prefix in ALLOWED_IP_PREFIXES)
#    if not allowed:
#        logger.warning(f"❌ IP {ip} не разрешён — не кампусный")
#    return allowed

@csrf_exempt
def webapp_checkin_static(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)

    try:
        if not request.body:
            return JsonResponse({"error": "Пустое тело запроса"}, status=400)
        try:
            data = json.loads(request.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return JsonResponse({"error": "Некорректный JSON"}, status=400)

        try:
            action_id = uuid.UUID(str(data.get("action_id")))
        except (TypeError, ValueError, AttributeError):
            return JsonResponse({"error": "Некорректный или отсутствующий action_id"}, status=400)

        source = data.get("source")
        if source not in {
            AttendanceAction.Source.TELEGRAM_BOT,
            AttendanceAction.Source.TELEGRAM_WEBAPP,
            AttendanceAction.Source.OTHER,
        }:
            return JsonResponse({"error": "Некорректный source"}, status=400)

        def optional_int(name):
            value = data.get(name)
            return int(value) if value not in (None, "") else None

        try:
            telegram_user_id = optional_int("telegram_user_id")
            if telegram_user_id is None:
                telegram_user_id = optional_int("telegram_id")
            update_id = optional_int("update_id")
            message_id = optional_int("message_id")
            chat_id = optional_int("chat_id")
        except (TypeError, ValueError):
            return JsonResponse({"error": "Некорректные идентификаторы Telegram"}, status=400)

        if source == AttendanceAction.Source.TELEGRAM_BOT:
            required_ids = (telegram_user_id, update_id, message_id, chat_id)
            signature = request.headers.get("X-Attendance-Signature")
            if any(value is None for value in required_ids) or not verify_attendance_signature(data, signature):
                return JsonResponse({"error": "Недействительная подпись запроса бота"}, status=403)
        elif request.path.endswith("/webapp/"):
            # The internal bot endpoint is never trusted merely because a caller
            # supplied a source header/body field.
            return JsonResponse({"error": "Для /webapp/ требуется подписанный запрос бота"}, status=403)

        phone = data.get("phone")
        user_agent = str(data.get("userAgent", ""))[:1000]
        location = data.get("location")
        correlation_id = str(data.get("correlation_id") or "")[:64]
        instance_id = str(data.get("instance_id") or "")[:128]
        try:
            lat = float(data["latitude"])
            lon = float(data["longitude"])
        except (KeyError, TypeError, ValueError):
            return JsonResponse({"error": "Некорректные координаты"}, status=400)

        if not phone and not telegram_user_id:
            return JsonResponse({"error": "Отсутствуют номер телефона и Telegram ID"}, status=403)

        ip = request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR")
        if is_suspicious_useragent(user_agent):
            WebAppAccessLog.objects.create(
                phone=phone,
                phone_matched="",
                user_id_matched=None,
                ip=ip,
                user_agent=user_agent,
                latitude=lat,
                longitude=lon,
                accuracy=data.get("accuracy"),
                reason="Suspicious device detected",
                success=False,
                campus=location
            )
            return JsonResponse({"error": "Suspicious device detected"}, status=403)

        teacher = None
        if phone:
            teacher = Teacher.objects.filter(phone_clean=normalize_phone(phone)).first()
        if teacher is None and telegram_user_id:
            teacher = Teacher.objects.filter(telegram_id=telegram_user_id).first()
        if not teacher:
            WebAppAccessLog.objects.create(
                user_id_matched=None,
                ip=ip,
                user_agent=user_agent,
                latitude=lat,
                longitude=lon,
                accuracy=data.get("accuracy"),
                reason="Номер не найден в базе kk",
                success=False,
                campus=location
            )
            return JsonResponse({"error": "Номер не найден в базе kk"}, status=403)

        if telegram_user_id:
            if not teacher.telegram_id:
                Teacher.objects.filter(pk=teacher.pk, telegram_id__isnull=True).update(
                    telegram_id=telegram_user_id
                )
                teacher.refresh_from_db(fields=["telegram_id"])
            if teacher.telegram_id != telegram_user_id:
                return JsonResponse({"error": "Telegram ID принадлежит другому сотруднику"}, status=403)

        campuses = list(Campus.objects.all())
        if not campuses:
            return JsonResponse({"error": "Корпуса не настроены"}, status=503)
        matched = sorted(
            (
                (campus, haversine_distance(lat, lon, campus.latitude, campus.longitude))
                for campus in campuses
            ),
            key=lambda item: item[1],
        )
        campus = next((item[0] for item in matched if item[1] <= item[0].radius), None)

        if not campus:
            WebAppAccessLog.objects.create(
                phone=phone,
                phone_matched=teacher.phone,
                user_id_matched=None, 
                ip=ip,
                user_agent=user_agent,
                latitude=lat,
                longitude=lon,
                accuracy=data.get("accuracy"),
                reason="Вне территории кампуса",
                success=False,
                campus=location
            )
            return JsonResponse({"error": "Вы не находитесь в кампусе"}, status=403)

        result = apply_attendance_action(
            action_id=action_id,
            source=source,
            teacher=teacher,
            campus_name=campus.name,
            telegram_user_id=telegram_user_id,
            update_id=update_id,
            message_id=message_id,
            chat_id=chat_id,
            correlation_id=correlation_id,
            instance_id=instance_id,
        )
        if not result.duplicate:
            WebAppAccessLog.objects.create(
                phone=phone,
                phone_matched=teacher.phone,
                user_id_matched=telegram_user_id,
                ip=ip,
                user_agent=user_agent,
                latitude=lat,
                longitude=lon,
                accuracy=data.get("accuracy"),
                reason=result.result_code,
                success=True,
                campus=campus.name,
            )
        return JsonResponse(
            {
                "status": result.status,
                "result": result.result_code,
                "visit_id": result.visit_id,
                "action_id": str(action_id),
                "duplicate": result.duplicate,
                "duplicate_reason": result.duplicate_reason,
            }
        )
    except AttendanceConflict as exc:
        return JsonResponse({"error": str(exc)}, status=409)
    except AttendanceTemporarilyUnavailable:
        return JsonResponse({"error": "Операция временно недоступна; безопасно повторите запрос"}, status=503)
    except Exception:
        logger.exception(
            "attendance_operation_failed",
            extra={
                "event": "attendance_operation_failed",
                "action_id": str(data.get("action_id", "")) if "data" in locals() else "",
                "source": data.get("source", "") if "data" in locals() else "",
                "reason": "unhandled_endpoint_error",
            },
        )
        return JsonResponse({"error": "Внутренняя ошибка сервера"}, status=500)

       

def qr_static(request):
    try:
        staturl = "http://127.0.0.1:8000/test?start=static_korpus-1"

        qrstat = qrcode.make(staturl)
        buffer_stat = BytesIO()
        qrstat.save(buffer_stat, format="PNG")
        statimgbase64 = base64.b64encode(buffer_stat.getvalue()).decode()

        return render(request, "attendance/qr_static_display.html", {
            "statimgbase64": statimgbase64,
        })
    except Exception as e:
        return HttpResponse(f"Ошибка: {e}", status=500)

def qr_redirect_static(request):
    return redirect("http://127.0.0.1:8000/test?start=static_korpus-1")

@csrf_exempt
def test_page(request):
    if request.method != "POST":
        return JsonResponse({
            "status": "success",
            "message": "Страница работает"
        })

    header = request.POST.get(
        "headerKey",
        ""
    ).strip()

    message = request.POST.get(
        "messageKey",
        ""
    ).strip()

    attachment = request.FILES.get(
        "attachment"
    )

    # =====================================================
    # ПОЛУЧАЕМ ТЕЛЕФОНЫ
    # =====================================================

    try:
        phones = json.loads(
            request.POST.get(
                "phones",
                "[]"
            )
        )

    except (
        json.JSONDecodeError,
        TypeError
    ):
        return JsonResponse(
            {
                "status": "error",
                "message": (
                    "Неверный список телефонов"
                )
            },
            status=400
        )

    if not isinstance(phones, list):
        return JsonResponse(
            {
                "status": "error",
                "message": (
                    "Телефоны должны быть "
                    "переданы списком"
                )
            },
            status=400
        )

    # =====================================================
    # ПРОВЕРЯЕМ ПОЛЯ
    # =====================================================

    if not header or not message:
        return JsonResponse(
            {
                "status": "error",
                "message": (
                    "Не заполнена тема "
                    "или сообщение"
                )
            },
            status=400
        )

    if not phones:
        return JsonResponse(
            {
                "status": "error",
                "message": (
                    "Не выбран получатель"
                )
            },
            status=400
        )

    # Максимальный размер файла — 50 МБ
    if (
        attachment
        and attachment.size > 50 * 1024 * 1024
    ):
        return JsonResponse(
            {
                "status": "error",
                "message": (
                    "Размер файла превышает 50 МБ"
                )
            },
            status=400
        )

    # =====================================================
    # НОРМАЛИЗУЕМ ТЕЛЕФОНЫ
    # =====================================================

    normalized_phones = []

    for phone in phones:
        if not phone:
            continue

        normalized_phone = normalize_phone(phone)

        if normalized_phone:
            normalized_phones.append(
                normalized_phone
            )

    if not normalized_phones:
        return JsonResponse(
            {
                "status": "error",
                "message": (
                    "Не найден корректный "
                    "номер телефона"
                )
            },
            status=400
        )

    # =====================================================
    # ПОЛУЧАЕМ СОТРУДНИКОВ
    # =====================================================

    teachers = (
        Teacher.objects
        .filter(
            phone_clean__in=normalized_phones,
            telegram_id__isnull=False
        )
    )

    if not teachers.exists():
        return JsonResponse(
            {
                "status": "error",
                "message": (
                    "У выбранного сотрудника "
                    "не найден Telegram ID"
                )
            },
            status=400
        )

    # =====================================================
    # ФОРМИРУЕМ ТЕКСТ
    # =====================================================

    text = (
        f"📢 Тема: {header}\n\n"
        f"{message}"
    )

    sent_messages = 0
    sent_files = 0
    failed = 0

    # =====================================================
    # ОТПРАВКА
    # =====================================================

    for teacher in teachers:
        telegram_id = teacher.telegram_id

        # Запись нужна до отправки, потому что её ID
        # передаётся в callback_data кнопки
        try:
            history_item = (
                MessageHistory.objects.create(
                    recipient=teacher,
                    subject=header,
                    message=message,
                    attachment_name=(
                        attachment.name
                        if attachment
                        else ""
                    ),
                    telegram_message_id=None,
                    file_sent=False,
                    read_at=None
                )
            )

        except Exception as error:
            failed += 1

            print(
                "Ошибка создания истории "
                f"для {telegram_id}:",
                error
            )

            # Без записи истории нельзя создать
            # рабочую кнопку подтверждения
            continue

        # =================================================
        # ОТПРАВЛЯЕМ ТЕКСТ С КНОПКОЙ
        # =================================================

        try:
            message_response = requests.post(
                (
                    "https://api.telegram.org/"
                    f"bot{BOT_TOKEN}/sendMessage"
                ),
                json={
                    "chat_id": int(telegram_id),
                    "text": text,
                    "reply_markup": {
                        "inline_keyboard": [
                            [
                                {
                                    "text": "✅ Прочитал",
                                    "callback_data": (
                                        "message_read:"
                                        f"{history_item.pk}"
                                    )
                                }
                            ]
                        ]
                    }
                },
                timeout=20
            )

            try:
                message_result = (
                    message_response.json()
                )

            except ValueError:
                message_result = {
                    "ok": False,
                    "description": (
                        message_response.text
                    )
                }

        except requests.RequestException as error:
            failed += 1

            # Telegram не получил сообщение,
            # поэтому запись истории удаляем
            history_item.delete()

            print(
                "Ошибка запроса сообщения "
                f"для {telegram_id}:",
                error
            )

            continue

        if not (
            message_response.ok
            and message_result.get("ok")
        ):
            failed += 1

            history_item.delete()

            print(
                f"Ошибка сообщения для "
                f"{telegram_id}:",
                message_result
            )

            continue

        sent_messages += 1

        # =================================================
        # СОХРАНЯЕМ TELEGRAM MESSAGE ID
        # =================================================

        telegram_message_id = (
            message_result
            .get("result", {})
            .get("message_id")
        )

        history_item.telegram_message_id = (
            telegram_message_id
        )

        history_item.save(
            update_fields=[
                "telegram_message_id"
            ]
        )

        # =================================================
        # ОТПРАВЛЯЕМ ФАЙЛ
        # =================================================

        file_was_sent = False

        if attachment:
            attachment.seek(0)

            try:
                file_response = requests.post(
                    (
                        "https://api.telegram.org/"
                        f"bot{BOT_TOKEN}/sendDocument"
                    ),
                    data={
                        "chat_id": int(telegram_id)
                    },
                    files={
                        "document": (
                            attachment.name,
                            attachment.file,
                            (
                                attachment.content_type
                                or
                                "application/octet-stream"
                            )
                        )
                    },
                    timeout=60
                )

                try:
                    file_result = (
                        file_response.json()
                    )

                except ValueError:
                    file_result = {
                        "ok": False,
                        "description": (
                            file_response.text
                        )
                    }

            except requests.RequestException as error:
                failed += 1

                print(
                    "Ошибка запроса файла "
                    f"для {telegram_id}:",
                    error
                )

            else:
                if (
                    file_response.ok
                    and file_result.get("ok")
                ):
                    sent_files += 1
                    file_was_sent = True

                else:
                    failed += 1

                    print(
                        f"Ошибка файла для "
                        f"{telegram_id}:",
                        file_result
                    )

        # Сохраняем результат отправки файла
        history_item.file_sent = file_was_sent

        history_item.save(
            update_fields=[
                "file_sent"
            ]
        )

    # =====================================================
    # ФОРМИРУЕМ ОТВЕТ
    # =====================================================

    if sent_messages == 0:
        return JsonResponse(
            {
                "status": "error",
                "message": (
                    "Ни одному получателю "
                    "сообщение не отправлено"
                ),
                "failed": failed
            },
            status=400
        )

    if attachment:
        response_message = (
            f"Сообщение получили: "
            f"{sent_messages}. "
            f"Файл получили: "
            f"{sent_files}."
        )

    else:
        response_message = (
            f"Сообщение получили: "
            f"{sent_messages}."
        )

    return JsonResponse({
        "status": "success",
        "message": response_message,
        "sent_messages": sent_messages,
        "sent_files": sent_files,
        "failed": failed
    })

@staff_member_required
def message_read_statuses(request):
    raw_ids = request.GET.get("ids","")

    history_ids = []

    for value in raw_ids.split(","):
        try:
            history_ids.append(int(value))
        except ValueError:
            continue

    messages = MessageHistory.objects.filter(
        pk__in=history_ids
    )

    statuses = {}

    for item in messages:
        statuses[str(item.pk)] = {
            "is_read": item.read_at is not None,
            "read_at": (
                timezone.localtime(item.read_at)
                .strftime("%d.%m %H:%M")
                if item.read_at
                else None
            )
        }

    return JsonResponse({
        "status": "success",
        "messages": statuses
    })

@staff_member_required
def conversation_history(request, recipient_id):
    recipient = get_object_or_404(
        Teacher.objects.only(
            "id",
            "fio",
            "phone"
        ),
        pk=recipient_id
    )

    try:
        cursor = int(request.GET.get("cursor", "0"))
    except (TypeError, ValueError):
        return JsonResponse(
            {
                "status": "error",
                "message": "Неверный cursor"
            },
            status=400
        )

    page_size = 20

    history_queryset = (
        MessageHistory.objects
        .filter(recipient_id=recipient_id)
        .only(
            "id",
            "subject",
            "message",
            "attachment_name",
            "created_at",
            "read_at",
        )
        .order_by("-id")
    )

    # Загружаем сообщения, которые старше последнего
    # уже показанного сообщения.
    if cursor > 0:
        history_queryset = history_queryset.filter(
            id__lt=cursor
        )

    # Берём на одну запись больше, чтобы понять,
    # осталась ли следующая страница.
    history_items = list(
        history_queryset[:page_size + 1]
    )

    has_more = len(history_items) > page_size
    history_items = history_items[:page_size]

    messages = []

    for history_item in history_items:
        messages.append({
            "id": history_item.pk,
            "subject": history_item.subject,
            "message": history_item.message,
            "attachment_name": (
                history_item.attachment_name or ""
            ),
            "created_at": timezone.localtime(
                history_item.created_at
            ).strftime("%d.%m.%Y %H:%M"),
            "is_read": history_item.read_at is not None,
            "read_at": (
                timezone.localtime(
                    history_item.read_at
                ).strftime("%d.%m.%Y %H:%M")
                if history_item.read_at
                else None
            ),
        })

    next_cursor = (
        history_items[-1].pk
        if has_more and history_items
        else None
    )

    return JsonResponse({
        "status": "success",
        "recipient": {
            "id": recipient.pk,
            "fio": recipient.fio,
            "phone": recipient.phone or "",
        },
        "messages": messages,
        "pagination": {
            "has_more": has_more,
            "next_cursor": next_cursor,
        },
    })
