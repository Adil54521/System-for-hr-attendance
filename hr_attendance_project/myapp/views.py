from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from myapp.models import Teacher, VisitLog, WebAppAccessLog, SuspiciousAccessLog
from django.contrib.auth.decorators import user_passes_test
from django.conf import settings
import json
from myapp.urls import *
import logging
import openpyxl
from django.http import HttpResponse
from django.shortcuts import render
import qrcode
from io import BytesIO
import base64
import hmac
import hashlib
from io import BytesIO
from dotenv import load_dotenv
from django.http import HttpResponse
import os
from geopy.distance import geodesic
from django.shortcuts import redirect
from django.views.decorators.http import require_GET
from django.views.decorators.csrf import csrf_protect
from datetime import datetime, date, timedelta
from urllib.parse import quote
from django.core.cache import cache
from django.core import serializers
import uuid, time
import asyncio
from aiogram import Bot, Dispatcher
from django.http import HttpResponseForbidden
from asgiref.sync import async_to_sync
from myapp.utilis import normalize_phone
from myapp.tabel import ExportToTabel 
from django.utils import timezone
import requests
import traceback
from django.core.serializers.json import DjangoJSONEncoder
from collections import defaultdict
import sys
from logging.handlers import RotatingFileHandler
from django.views.decorators.http import require_http_methods
dotenv_path = r"C:\HR_Site\hr_attendance_project\key.env"

load_dotenv(dotenv_path)

BOT_TOKEN = os.getenv("BOT_TOKEN")
logger = logging.getLogger("hr_ai_log")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = RotatingFileHandler(
        "hr_ai_log.log",
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8"
    )

    formatter = logging.Formatter(
        "%(asctime)s | %(message)s"
    )

    handler.setFormatter(formatter)
    logger.addHandler(handler)
QR_SECRET_KEY = os.getenv("QR_SECRET_KEY")
ALLOWED_IPS = ["193.193.226.139", "127.0.0.1", "212.96.71.106"]
ALLOWED_IP_PREFIXES = ["192.168.88.", "10.10.", "193.193.226."]   # локальные сети
RATE_LIMIT_SECONDS = 60   # интервал в секундах
RATE_LIMIT_MAX = 5        # максимум запросов за интервал
REDIRECT_ENABLED = True
WEBAPP_COOLDOWN = 300

SUSPICIOUS_PATTERNS = [
    "x86", "emulator", "genymotion", "test-keys",
    "vbox", "build/qemu", "virtual", "debug", "root"
]

base_url = "https://generativelanguage.googleapis.com/v1beta"
ai_model = "models/gemini-3.5-flash"

api_key = os.getenv("GEMINI_API_KEY")
cache_name = None

def all_data_send():
    today = date.today()
    start_of_year = date(today.year, 1, 1)

    qs = VisitLog.objects.filter(
        date__range=(start_of_year, today)
    ).select_related("teacher").order_by("date")

    result = []
    for r in qs:
        # Получаем attendance как разницу между time_out и time_in
        attendance_str = None
        if r.time_in and r.time_out:
            delta = datetime.combine(date.min, r.time_out) - datetime.combine(date.min, r.time_in)
            total_seconds = int(delta.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            attendance_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        result.append({
            "date": r.date.strftime("%Y-%m-%d") if r.date else None,
            "teacher_fio": r.teacher.fio,
            "time_in": r.time_in.strftime("%H:%M:%S") if r.time_in else None,
            "time_out": r.time_out.strftime("%H:%M:%S") if r.time_out else None,
            "attendance": attendance_str,
        })
    with open("dt.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

#all_data_send()  

def data_for_specific_day(
    target_date=None,
    date_from=None,
    date_to=None,
    teacher_fio=None,
    time_in_after=None,
    time_out_before=None,
    attendance_range=None  # новый аргумент
):
    # Загружаем данные из JSON
    with open('dt.json', 'r', encoding='utf-8') as f:
        data = json.load(f)

    filtered = []

    for r in data:
        # Преобразуем строки в объекты даты/времени для сравнения
        r_date = datetime.strptime(r["date"], "%Y-%m-%d").date() if r.get("date") else None
        r_time_in = datetime.strptime(r["time_in"], "%H:%M:%S").time() if r.get("time_in") else None
        r_time_out = datetime.strptime(r["time_out"], "%H:%M:%S").time() if r.get("time_out") else None
        r_attendance = r.get("attendance")

        # Фильтрация по target_date
        if target_date:
            td = datetime.strptime(target_date, "%Y-%m-%d").date()
            if r_date != td:
                continue

        # Фильтрация по диапазону дат
        if date_from and date_to:
            df = datetime.strptime(date_from, "%Y-%m-%d").date()
            dt = datetime.strptime(date_to, "%Y-%m-%d").date()
            if not (df <= r_date <= dt):
                continue

        # Фильтрация по ФИО
        if teacher_fio and teacher_fio.lower() not in r.get("teacher_fio", "").lower():
            continue

        # Фильтрация по времени прихода
        if time_in_after:
            tia = datetime.strptime(time_in_after, "%H:%M:%S").time()
            if not r_time_in or r_time_in < tia:
                continue

        # Фильтрация по времени ухода
        if time_out_before:
            tob = datetime.strptime(time_out_before, "%H:%M:%S").time()
            if not r_time_out or r_time_out > tob:
                continue

        # Фильтрация по attendance
        if attendance_range and r_attendance:
            start_str, end_str = attendance_range.split('-')
            start_sec = sum(int(x) * 60 ** i for i, x in enumerate(reversed(start_str.split(':'))))
            end_sec = sum(int(x) * 60 ** i for i, x in enumerate(reversed(end_str.split(':'))))
            r_sec = sum(int(x) * 60 ** i for i, x in enumerate(reversed(r_attendance.split(':'))))
            if not (start_sec <= r_sec <= end_sec):
                continue

        filtered.append(r)

    return filtered

def fetch(request, user_meta: dict | None = None):
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)

    try:
        meta = user_meta or {}
        # 1. Начальные проверки
        user_input = request.POST.get("ai_q", "").strip()
        if not user_input:
            return JsonResponse({"error": "Empty input"}, status=400)
        
        if not api_key:
            return JsonResponse({"error": "API key missing"}, status=500)
        current_today = datetime.today().date()
        yesterday = current_today - timedelta(days=1)
        print(current_today)
        url = f"{base_url}/{ai_model}:generateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        }
        # Объект с инструментами (выносим в переменную, так как он нужен в обоих запросах)
        tools_config = {
            "function_declarations": [
                {
                    "name": "data_for_specific_day",
                    "description": "Returns teachers' attendance records. Use this for ANY queries about arrival time, latecomers, working hours, or presence/absence.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "date": {
                                "type": "string",
                                "description": f"The exact date in YYYY-MM-DD format. Today is {current_today}. If user says {yesterday}, calculate it relative to this date."
                            },
                            "date_from": {
                                "type": "string",
                                "description": "Start date of a period (YYYY-MM-DD). Use for 'since Monday', 'from the beginning of the month', etc."
                            },
                            "date_to": {
                                "type": "string",
                                "description": "End date of a period (YYYY-MM-DD). Use for 'until Friday', 'to the end of the week', etc."
                            },
                            "teacher_fio": {
                                "type": "string",
                                "description": "Any mention of an teachers's name or surname also those combinations of name + surname, surname + name. Pass it exactly as written (e.g., 'Shukraliev')."
                            },
                            "time_in_after": {
                                "type": "string",
                                "description": "Time in HH:MM:SS. Fill if query is about latecomers or those who arrived AFTER a specific time (e.g., 'after 09:00')."
                            },
                            "time_out_before": {
                                "type": "string",
                                "description": "Time in HH:MM:SS. Fill if query is about those who left EARLIER than expected."
                            },
                            "attendance_range": {
                                "type": "string",
                                "description": "Duration criteria in HH:MM:SS. If user asks 'worked less than 5 hours', pass '05:00:00'."
                            }
                        },
                        "required": [] 
                    }
                }
            ]
        }
        generation_config = {
            "temperature": 0.1, # Снижаем для стабильности вызова функций
            "topP": 0.95,
            "maxOutputTokens": 1024
        }
        system_instruction = {
            "role": "system", # В актуальном API роль для инструкций обычно system или передается отдельно
            "parts": [{"text": f"""You are an attendance assistant working with structured JSON records.

                                 Users ask questions in natural language, not JSON.
                                 You must extract meaning by word matching.
                                 
                                 Data fields:
                                 - date — working date
                                 - teacher_fio — full teacher name
                                 - time_in — arrival time
                                 - time_out — leaving time
                                 - attendance — worked duration (already calculated or null)
                                 
                                 Rules:
                                 
                                 Name matching:
                                 - Match teacher by partial name match
                                 - Match by surname only, name only, or full name
                                 - Ignore word order
                                 - Example: "Адильхан", "Шукралиев", "Адильхан Шукралиев" → same person
                                 
                                 Date matching:
                                 - Extract dates from phrases like:
                                   "15 января", "вчера", "сегодня", "15.01.2026"
                                 - Convert to YYYY-MM-DD
                                 
                                 Logic:
                                 - Questions about "сколько отработал" → use attendance
                                 - If attendance is null → say worked time is not available
                                 - DO NOT calculate durations yourself
                                 - Use only provided data
                                 - Do not invent records"""}]
        }

        # --- ПЕРВЫЙ ЗАПРОС ---
        payload = {
            "contents": [{"role": "user", "parts": [{"text": user_input}]}],
            "tools": [tools_config],
            "tool_config": {"function_calling_config": {"mode": "AUTO"}},
            "systemInstruction": system_instruction
        }

        response = requests.post(url, headers=headers, json=payload, timeout=90)
        response.raise_for_status()
        result = response.json()
        usage = result.get("usageMetadata", {})
        candidate = result.get("candidates", [{}])[0]
        model_message = candidate.get("content", {})
        parts = model_message.get("parts", [])
        logger.info(
            f"AI_USAGE_RESPONSE | {usage} | {candidate}"
        )

        if not parts:
            return JsonResponse({"answer": "Пустой ответ модели"})

        # --- ПРОВЕРКА НА ВЫЗОВ ФУНКЦИИ ---
        if "functionCall" in parts[0]:
            fc = parts[0]["functionCall"]
            func_name = fc.get("name")
            func_args = fc.get("args", {})

            # Выполняем вашу логику БД
            if func_name == "data_for_specific_day":
                if "date" in func_args:
                    func_args["target_date"] = func_args.pop("date")
                
                tool_result = data_for_specific_day(**func_args)
            else:
                tool_result = {"error": "Unknown function"}

            # --- ВТОРОЙ ЗАПРОС (Передача результата) ---
            # КРИТИЧНО: В contents должны быть: 1. User query, 2. Model's functionCall, 3. FunctionResponse
            second_payload = {
                "contents": [
                    {"role": "user", "parts": [{"text": user_input}]},
                    model_message, # ЭТО ТОТ САМЫЙ ШАГ: возвращаем модели её же запрос
                    {
                        "role": "function",
                        "parts": [{
                            "functionResponse": {
                                "name": func_name,
                                "response": {"content": tool_result} # Результат ОБЯЗАТЕЛЬНО должен быть объектом {}
                            }
                        }]
                    }
                ],
                "tools": [tools_config],
                "generationConfig": generation_config,
                "systemInstruction": system_instruction
            }

            second_response = requests.post(url, json=second_payload, timeout=120)
            
            if second_response.status_code != 200:
                print("DEBUG Error Body:", second_response.text)
                second_response.raise_for_status()

            second_json = second_response.json()
            final_text = (
                second_json.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "Не удалось обработать данные")
            )
            
            return JsonResponse({"answer": final_text})

        # Если модель сразу ответила текстом
        if "text" in parts[0]:
            return JsonResponse({"answer": parts[0]["text"]})

        return JsonResponse({"answer": "Неизвестный формат ответа"})

    except Exception:
        logger.exception("Ошибка при обработке запроса Gemini")
        return JsonResponse(
            {"error": "Внутренняя ошибка сервера"},
            status=500
        )    
@csrf_exempt
def test_headers(request):
    return JsonResponse({
        "HTTP_X_FORWARDED_FOR": request.META.get("HTTP_X_FORWARDED_FOR"),
        "HTTP_X_REAL_IP": request.META.get("HTTP_X_REAL_IP"),
        "REMOTE_ADDR": request.META.get("REMOTE_ADDR"),
        "ALL_META": {k: v for k, v in request.META.items() if 'FORWARDED' in k or 'REAL' in k or 'REMOTE' in k}
    })
    
def get_bot():
    return Bot(token=os.getenv("BOT_TOKEN"))
    
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

def is_fake_device(user_agent: str) -> bool:
    ua = user_agent.lower()

    # 🤖 Разрешаем Telegram-Android на реальных устройствах Samsung
    if "telegram-android" in ua and ("samsung" in ua or "xiaomi" in ua):
        return False

    suspicious = ["emulator", "genymotion", "x86", "vbox", "virtual", "debug", "root", "test-keys"]
    for keyword in suspicious:
        if keyword in ua:
            logger.warning(f"❌ Фейковое устройство: содержит '{keyword}'")
            return True

    return False

def is_hr(user):
    return user.is_authenticated and user.groups.filter(name="HR").exists()

@user_passes_test(is_hr)
def admin_panel(request):
    visits = VisitLog.objects.select_related('teacher').order_by('-date', '-time_in')

    return render(request, 'attendance/admin_panel.html', {
        'visits': visits,
        'show_absent': request.GET.get("absent") == "1",
        'today': timezone.localdate(),
    })
    
@user_passes_test(is_hr)
def export_excel(request):
    # создаём экземпляр сервиса
    exporter = ExportToTabel(request)
    exporter.excelOutPut()
    exporter.placeDate()
    exporter.placeNameJob(request) 

    # формируем HTTP-ответ
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    filename = f"Табель_{datetime.today().strftime('%Y-%m-%d')}.xlsx"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    exporter.workbook.save(response)
    return response

def check_rate_limit(ip: str) -> bool:
    key = f"ratelimit:{ip}"
    now = time.time()

    history = cache.get(key, [])
    history = [t for t in history if now - t < RATE_LIMIT_SECONDS]

    if len(history) >= RATE_LIMIT_MAX:
        return False

    history.append(now)
    cache.set(key, history, timeout=RATE_LIMIT_SECONDS)
    return True  
    
@csrf_exempt
def webapp_checkin(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)

    try:
        raw_body = request.body
        if not raw_body:
            return JsonResponse({"error": "Пустое тело запроса"}, status=400)

        try:
            data = json.loads(raw_body)
        except json.JSONDecodeError:
            logger.error(f"Ошибка декодирования JSON: {raw_body}")
            return JsonResponse({"error": "Некорректный JSON"}, status=400)

        if not isinstance(data, dict):
            logger.error(f"Получен не-словарь: {data}")
            return JsonResponse({"error": "Неверный формат JSON"}, status=400)
       
        phone = data.get("phone", "").strip()
        user_id = data.get("user_id")
        if not phone:
            return JsonResponse({"error": "Отсутствует номер телефона"}, status=403)

        normalized_phone = normalize_phone(phone)
        lat = float(data.get("latitude", 0))
        lon = float(data.get("longitude", 0))
        accuracy = float(data.get("accuracy", 9999))
        user_agent = data.get("userAgent", "")
        ip = request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR")
        # ✅ COOLDOWN
        allowed, wait = check_webapp_cooldown(normalized_phone)
        if not allowed:
            return JsonResponse({
                "error": f"Слишком часто. Подождите {wait} сек."
            }, status=429)
        logger.warning(f"IP-адрес клиента: {ip}")
        logger.warning(f"WebApp вход: phone={phone}, lat={lat}, lon={lon}, acc={accuracy}, IP={ip}, UA={user_agent}")

        teacher = Teacher.objects.filter(phone_clean=normalized_phone).first()
        phone_matched = teacher.phone if teacher else ""

        # Проверка на эмулятор / root
        if is_suspicious_useragent(user_agent):
            SuspiciousAccessLog.objects.create(
                ip_address=ip,
                user_agent=user_agent,
                reason="Developer mode / emulator suspected",
                blocked=True
            )
            return JsonResponse({"error": "Suspicious device detected"}, status=403)

        # Проверка IP
        #if not is_ip_allowed(ip):
        #    WebAppAccessLog.objects.create(
        #        phone=phone,
        #        phone_matched=phone_matched,
        #        ip=ip,
        #        user_agent=user_agent,
        #        latitude=lat,
        #        longitude=lon,
        #        accuracy=accuracy,
        #        reason="IP не входит в кампусную сеть",
        #        success=False
        #    )
        #    return JsonResponse({"error": "Вы не подключены к университетской сети"}, status=403)

        if not teacher:
            WebAppAccessLog.objects.create(
                phone=phone,
                phone_matched="",
                ip=ip,
                user_agent=user_agent,
                latitude=lat,
                longitude=lon,
                accuracy=accuracy,
                reason="Номер не найден в базе",
                success=False,
                campus=""
            )
            return JsonResponse({"error": "Номер не найден в базе"}, status=403)

        # Проверка точности GPS
        if accuracy > 2500:
            WebAppAccessLog.objects.create(
                phone=phone,
                phone_matched=phone_matched,
                ip=ip,
                user_agent=user_agent,
                latitude=lat,
                longitude=lon,
                accuracy=accuracy,
                reason=f"Слишком низкая точность GPS: {accuracy}",
                success=False,
                campus=""
            )
            return JsonResponse({"error": "Низкая точность геолокации"}, status=403)

        # Геолокация кампусов
        campus_locations = {
            "korpus-1": (53.289553, 69.392535),
            "korpus-2": (53.289337, 69.391170),
        }

        matched_location = None
        telega_id = None
        for loc, coords in campus_locations.items():
            radius = min(150, 50 + accuracy)
            if geodesic((lat, lon), coords).meters < radius:
                matched_location = loc
                break

        if not matched_location and telega_id:
            WebAppAccessLog.objects.create(
                phone=phone,
                phone_matched=phone_matched,
                ip=ip,
                user_agent=user_agent,
                latitude=lat,
                longitude=lon,
                accuracy=accuracy,
                reason="Геолокация не в кампусе",
                success=False,
                campus=""
            )
            return JsonResponse({"error": "Вы находитесь вне кампуса"}, status=403)

        now = timezone.localtime(timezone.now())
        today = now.date()
        visit = VisitLog.objects.filter(teacher=teacher, date=today).first()

        if not visit:
            VisitLog.objects.create(
                teacher=teacher,
                date=today,
                time_in=now,
                location=matched_location
            )
            WebAppAccessLog.objects.create(
                phone=phone,
                phone_matched=phone_matched,
                ip=ip,
                user_agent=user_agent,
                latitude=lat,
                longitude=lon,
                accuracy=accuracy,
                reason="Успешный вход",
                success=True,
                campus=matched_location
            )
            return JsonResponse({"status": f"Вход зарегистрирован. Корпус: {matched_location}"})

        elif visit and not visit.time_out:
            visit.time_out = now.time()   # сохраним только часы-минуты
            
            if visit.time_in:
                # собираем полные datetime
                start_dt = datetime.combine(visit.date, visit.time_in)
                end_dt = datetime.combine(visit.date, now.time())
            
                # если сотрудник вышел после полуночи → переносим дату
                if end_dt < start_dt:
                    end_dt = end_dt.replace(day=end_dt.day + 1)
            
                visit.attendance = end_dt - start_dt
            
            visit.save()

            WebAppAccessLog.objects.create(
                phone=phone,
                phone_matched=phone_matched,
                ip=ip,
                user_agent=user_agent,
                latitude=lat,
                longitude=lon,
                accuracy=accuracy,
                reason="Успешный выход",
                success=True,
                campus=visit.location or matched_location
            )
            return JsonResponse({"status": f"Выход зарегистрирован. Корпус: {visit.location or matched_location}"})

        else:
            return JsonResponse({"status": f"Вы уже отметились сегодня. Корпус: {visit.location or matched_location}"})

    except Exception as e:
        logger.exception("Ошибка при WebApp check-in")
        return JsonResponse({"error": str(e)}, status=500)
        
def redirect_to_bot(request):
    ip = request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR")
    qr_id = request.GET.get("qr_id")  # ?qr_id=abc123
    
    if not qr_id:
        print("❌ qr_id отсутствует")
        return HttpResponse("❌ QR-код не содержит параметров", status=400)

    #if not is_ip_allowed(ip):
    #    print(f"⛔ Недопустимый IP: {ip}")
    #    return HttpResponse("⛔ Вы не подключены к университетской сети", status=403)

    # ✅ Передаём только ID, без полного URL
    return render(request, "attendance/qr_redirect.html", {
        "qr_id": qr_id
    })
        
def qr_handler(request, location=None):
    try:
        if not location:
            return HttpResponse("❌ Локация не указана", status=400)

        qr_id = uuid.uuid4().hex[:8]
        print(f"✅ Сохраняю в кэш: qr:{qr_id}")
        cache.set(f"qr:{qr_id}", {
            "location": location,
            "created_at": int(time.time())
        }, timeout=60)  # 60 сек живёт

        qr_url = f"https://hrattendance.kuam.kz/qr_redirect/?qr_id={qr_id}"  # ✅ передаём qr_id

        qr = qrcode.make(qr_url)
        buffer = BytesIO()
        qr.save(buffer, format="PNG")
        img_base64 = base64.b64encode(buffer.getvalue()).decode()

        return render(request, "attendance/qr_display.html", {
            "img_base64": img_base64,
        })

    except Exception as e:
        logger.exception("❌ Ошибка в qr_handler:")
        return HttpResponse(f"❌ Ошибка: {e}", status=500)
        
def check_webapp_cooldown(key: str):
    cache_key = f"webapp_cd:{key}"
    last_time = cache.get(cache_key)

    now = time.time()

    if last_time:
        remaining = int(WEBAPP_COOLDOWN - (now - last_time))
        if remaining > 0:
            return False, remaining

    cache.set(cache_key, now, timeout=WEBAPP_COOLDOWN)
    
    return True, 0
def qr_secure(request, location):
    ip = request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR")
    print(f"👀 IP пользователя: {ip}")
    logger.info(f"🌐 Попытка доступа к QR: {ip} для {location}")

    #if not is_ip_allowed(ip):
    #    logger.warning(f"⛔: {ip} не входит в разрешённые диапазоны")
    #    return HttpResponseForbidden("⛔")

    # если всё ок — сгенерируй QR
    return qr_handler(request, location)
@csrf_exempt
def webapp_page(request):
    phone = request.GET.get("phone", "")
    return render(request, "attendance/index.html", {"phone": phone})
