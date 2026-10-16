import random
from datetime import datetime, time
from django.core.management.base import BaseCommand
from myapp.models import Teacher, VisitLog

class Command(BaseCommand):
    help = 'Создаёт случайный VisitLog для преподавателя с учётом выходных и праздников РК'

    # Список праздничных дней в формате YYYY-MM-DD
    HOLIDAYS = [
        "2025-01-01",  # Новый год
        "2025-03-08",  # 8 марта
        "2025-05-01",  # День труда
        "2025-05-07",  # День защитника Отечества
        "2025-05-28",  # День Конституции
        "2025-07-06",  # День столицы
        "2025-12-16",  # День независимости
    ]

    def handle(self, *args, **kwargs):
        today = datetime.today().date()

        # Проверка на выходной (суббота = 5, воскресенье = 6)
        if today.weekday() >= 5:
            self.stdout.write("Сегодня выходной, запись не создаётся.")
            return

        # Проверка на праздничный день
        if today.strftime("%Y-%m-%d") in self.HOLIDAYS:
            self.stdout.write("Сегодня праздничный день, запись не создаётся.")
            return

        # Ищем преподавателя
        teacher = Teacher.objects.filter(fio="Бекишев Куандык Омарович").first()
        if not teacher:
            self.stdout.write("Teacher not found")
            return

        # Генерация случайного времени прихода (08:55 – 09:05)
        start_in = 8 * 60 + 55
        end_in = 9 * 60 + 5
        minutes_in = random.randint(start_in, end_in)
        random_time_in = time(minutes_in // 60, minutes_in % 60)

        # Генерация случайного времени ухода (17:50 – 18:10)
        start_out = 17 * 60 + 50
        end_out = 18 * 60 + 10
        minutes_out = random.randint(start_out, end_out)
        random_time_out = time(minutes_out // 60, minutes_out % 60)

        # Вычисляем рабочее время
        dt_in = datetime.combine(today, random_time_in)
        dt_out = datetime.combine(today, random_time_out)
        work_time = dt_out - dt_in  # timedelta

        location = "korpus-1"

        # Создаём VisitLog, если ещё нет записи на сегодня
        visit_log, created = VisitLog.objects.get_or_create(
            teacher=teacher,
            date=today,
            defaults={
                'time_in': random_time_in,
                'time_out': random_time_out,
                'attendance': work_time,
                'location': location,
            },
        )

        if created:
            self.stdout.write(
                f"VisitLog создан: {random_time_in} – {random_time_out} | Рабочее время: {work_time}"
            )
        else:
            self.stdout.write("VisitLog на сегодня уже существует.")
