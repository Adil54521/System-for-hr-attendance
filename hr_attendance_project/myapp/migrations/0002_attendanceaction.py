import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("myapp", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="AttendanceAction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action_id", models.UUIDField(unique=True)),
                ("source", models.CharField(choices=[("telegram_bot", "Telegram bot"), ("telegram_webapp", "Telegram WebApp"), ("other", "Other")], max_length=32)),
                ("telegram_user_id", models.BigIntegerField(blank=True, null=True)),
                ("update_id", models.BigIntegerField(blank=True, null=True)),
                ("message_id", models.BigIntegerField(blank=True, null=True)),
                ("chat_id", models.BigIntegerField(blank=True, null=True)),
                ("correlation_id", models.CharField(blank=True, max_length=64)),
                ("status", models.CharField(choices=[("processing", "Processing"), ("succeeded", "Succeeded")], max_length=16)),
                ("result_code", models.CharField(blank=True, max_length=32)),
                ("response_status", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("teacher", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="myapp.teacher")),
                ("visit", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="myapp.visitlog")),
            ],
        ),
        migrations.AddConstraint(
            model_name="attendanceaction",
            constraint=models.UniqueConstraint(condition=models.Q(("update_id__isnull", False)), fields=("source", "update_id"), name="uniq_attendance_source_update"),
        ),
        migrations.AddConstraint(
            model_name="attendanceaction",
            constraint=models.UniqueConstraint(condition=models.Q(("chat_id__isnull", False), ("message_id__isnull", False)), fields=("source", "chat_id", "message_id"), name="uniq_attendance_source_message"),
        ),
    ]
