from django.db import models
from myapp.utilis import normalize_phone
import datetime


class Campus(models.Model):
    name = models.CharField(max_length=100, unique=True)
    latitude = models.FloatField()
    longitude = models.FloatField()
    radius = models.IntegerField(default=50)

    def __str__(self):
        return self.name

class Teacher(models.Model):
    fio = models.CharField("ФИО", max_length=255)
    job_title = models.CharField("Должность", max_length=255)
    date = models.DateField("Дата", default=datetime.date.today)
    phone = models.CharField("Телефон", max_length=20, unique=True, blank=True, null=True)
    phone_clean = models.CharField(max_length=20, blank=True)
    department = models.CharField("Отдел", max_length=255, blank=True, null=True)
    address = models.TextField("Адрес", null=True, blank=True)
    device_token = models.CharField("Токен устройства", max_length=64, blank=True, null=True)
    telegram_id = models.BigIntegerField(blank=True, null=True, unique=True)
    extra1 = models.CharField("Доп. поле 1", max_length=255, blank=True, null=True)
    extra2 = models.CharField("Доп. поле 2", max_length=255, blank=True, null=True)
    extra3 = models.CharField("Доп. поле 3", max_length=255, blank=True, null=True)
    
    def save(self, *args, **kwargs):
        self.phone_clean = normalize_phone(self.phone)
        super().save(*args, **kwargs)
        
    class Meta:
        verbose_name = "Сотрудник"
        verbose_name_plural = "Сотрудники"

    def __str__(self):
        return f"{self.fio} — {self.job_title}"
        

class VisitLog(models.Model):
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, verbose_name="Сотрудник")
    date = models.DateField("Дата")
    telegram_id = models.BigIntegerField("Telegram ID", blank=True, null=True)
    time_in = models.TimeField("Вход", null=True, blank=True)
    time_out = models.TimeField("Выход", null=True, blank=True)
    attendance = models.DurationField("Отработано", null=True, blank=True)
    check_gal = models.CharField("Статус", max_length=1, default='✔')
    location = models.CharField("Локация", max_length=100, blank=True, null=True)

    # 🆕 Новые поля:
    latitude = models.FloatField("Широта", null=True, blank=True)
    longitude = models.FloatField("Долгота", null=True, blank=True)
    ip = models.GenericIPAddressField("IP-адрес", null=True, blank=True)
    user_agent = models.TextField("User-Agent", blank=True)

    class Meta:
        verbose_name = "Запись посещения"
        verbose_name_plural = "Журнал посещений"

    def __str__(self):
        return f"{self.teacher.fio} — {self.date} {self.time_in} {self.time_out} {self.attendance} {self.location}"


class AttendanceAction(models.Model):
    class Source(models.TextChoices):
        TELEGRAM_BOT = "telegram_bot", "Telegram bot"
        TELEGRAM_WEBAPP = "telegram_webapp", "Telegram WebApp"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        PROCESSING = "processing", "Processing"
        SUCCEEDED = "succeeded", "Succeeded"

    action_id = models.UUIDField(unique=True)
    source = models.CharField(max_length=32, choices=Source.choices)
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE)
    visit = models.ForeignKey(VisitLog, null=True, blank=True, on_delete=models.SET_NULL)
    telegram_user_id = models.BigIntegerField(null=True, blank=True)
    update_id = models.BigIntegerField(null=True, blank=True)
    message_id = models.BigIntegerField(null=True, blank=True)
    chat_id = models.BigIntegerField(null=True, blank=True)
    correlation_id = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices)
    result_code = models.CharField(max_length=32, blank=True)
    response_status = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "update_id"],
                condition=models.Q(update_id__isnull=False),
                name="uniq_attendance_source_update",
            ),
            models.UniqueConstraint(
                fields=["source", "chat_id", "message_id"],
                condition=models.Q(chat_id__isnull=False, message_id__isnull=False),
                name="uniq_attendance_source_message",
            ),
        ]

class WebAppAccessLog(models.Model):
    phone_matched = models.CharField("Совпавший номер из базы", max_length=20, blank=True, null=True)
    phone = models.CharField("Телефон (номер с которого заходили)", max_length=20, blank=True, null=True)  # ✅ добавили поле
    user_id_matched = models.BigIntegerField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    accuracy = models.FloatField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    success = models.BooleanField(default=False)
    reason = models.TextField(blank=True)
    campus = models.CharField(max_length=50, blank=True)

    @classmethod
    def log(cls, *, phone="", phone_matched="", ip=None, user_agent="", latitude=None, longitude=None, accuracy=None, success=False, reason="", campus=""):
        return cls.objects.create(
            phone=phone,
            phone_matched=teacher.phone if teacher else phone,
            ip=ip,
            user_agent=user_agent,
            latitude=latitude,
            longitude=longitude,
            accuracy=accuracy,
            success=success,
            reason=reason,
            campus=campus,
        )

class SuspiciousAccessLog(models.Model):
    ip_address = models.GenericIPAddressField("IP-адрес")
    user_agent = models.TextField("User-Agent", blank=True)
    timestamp = models.DateTimeField("Дата/время", auto_now_add=True)
    reason = models.CharField("Причина", max_length=255)
    blocked = models.BooleanField("Заблокирован", default=False)

    class Meta:
        verbose_name = "Подозрительная попытка входа"
        verbose_name_plural = "Подозрительные попытки"

    def __str__(self):
        status = "🚫" if self.blocked else "⚠️"
        return f"{status} {self.ip_address} — {self.reason[:40]}"


class AbiturientsAccessCount(models.Model):
    ip = models.GenericIPAddressField("IP-адрес",null=True, blank=True)
    user_agent = models.TextField("Пользовательский агент", blank=True)
    date = models.DateField("Дата", default=datetime.date.today)
    
    class Meta:
        verbose_name = "Запись абитуриентов"
        verbose_name_plural = "количество абитуриентов"

class MessageHistory(models.Model):
    recipient = models.ForeignKey(
        "Teacher",
        on_delete=models.CASCADE,
        related_name="message_history",
        verbose_name="Получатель"
    )

    subject = models.CharField(
        max_length=200,
        verbose_name="Тема сообщения"
    )

    message = models.TextField(
        verbose_name="Текст сообщения"
    )

    attachment_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Название файла"
    )

    telegram_message_id = models.BigIntegerField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="ID сообщения в Telegram"
    )

    file_sent = models.BooleanField(
        default=False,
        verbose_name="Файл отправлен"
    )

    read_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Дата подтверждения прочтения"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name="Дата отправки"
    )

    @property
    def is_read(self):
        return self.read_at is not None

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "История сообщения"
        verbose_name_plural = "История сообщений"

    def __str__(self):
        return (
            f"{self.recipient} — "
            f"{self.subject}"
        )