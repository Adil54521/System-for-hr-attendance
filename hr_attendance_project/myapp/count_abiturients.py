from .models import AbiturientsAccessCount
from django.http import HttpResponse
import qrcode
from io import BytesIO
import base64
from django.shortcuts import render, redirect

def qr_make(request):
    """
    Генерирует QR-код, ведущий на страницу отметки /qr-abiturients-status/
    """
    try:
        target_url = "https://hrattendance.kuam.kz/qr-abiturients-status/"

        qr_image = qrcode.make(target_url)
        buffer = BytesIO()
        qr_image.save(buffer, format="PNG")
        image_base64 = base64.b64encode(buffer.getvalue()).decode()

        return render(request, "attendance/abiturients_qr.html", {
            "imagebase": image_base64
        })
    except Exception as e:
        return HttpResponse(f"Ошибка при генерации QR: {e}", status=500)


def check_ip(request):
    """
    Когда пользователь открывает /qr-abiturients-status/,
    Django фиксирует IP и показывает результат.
    """
    try:
        # Определяем IP
        ip = request.META.get('HTTP_X_FORWARDED_FOR')
        if ip:
            ip = ip.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')

        user_agent = request.META.get('HTTP_USER_AGENT', '')

        # Проверяем, есть ли уже отметка
        if AbiturientsAccessCount.objects.filter(ip=ip).exists():
            return render(request, 'abiturient_status.html', {
                'success': False,
                'message': 'Вы уже отметились ранее 👋',
                'ip': ip
            })

        # Добавляем новую отметку
        AbiturientsAccessCount.objects.create(ip=ip, user_agent=user_agent)

        return render(request, 'abiturient_status.html', {
            'success': True,
            'message': '✅ Отметка успешно сохранена!',
            'ip': ip
        })

    except Exception as e:
        return render(request, 'abiturient_status.html', {
            'success': False,
            'message': f'Ошибка: {e}',
            'ip': None
        })