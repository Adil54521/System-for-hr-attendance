import logging
import os
from dataclasses import dataclass
from datetime import datetime

from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Q
from django.utils import timezone

from myapp.models import AttendanceAction, VisitLog


logger = logging.getLogger("attendance")


@dataclass(frozen=True)
class AttendanceResult:
    status: str
    result_code: str
    visit_id: int | None
    duplicate: bool
    duplicate_reason: str = ""


class AttendanceConflict(Exception):
    pass


class AttendanceTemporarilyUnavailable(Exception):
    pass


def _identity_query(*, action_id, source, update_id, chat_id, message_id):
    query = Q(action_id=action_id)
    if update_id is not None:
        query |= Q(source=source, update_id=update_id)
    if chat_id is not None and message_id is not None:
        query |= Q(source=source, chat_id=chat_id, message_id=message_id)
    return query


def _existing_result(
    *, action_id, source, teacher, telegram_user_id, update_id, chat_id, message_id
):
    action = AttendanceAction.objects.filter(
        _identity_query(
            action_id=action_id,
            source=source,
            update_id=update_id,
            chat_id=chat_id,
            message_id=message_id,
        )
    ).first()
    if action is None:
        return None
    if action.teacher_id != teacher.id:
        raise AttendanceConflict("action_id принадлежит другому сотруднику")
    if (
        action.telegram_user_id is not None
        and telegram_user_id is not None
        and action.telegram_user_id != telegram_user_id
    ):
        raise AttendanceConflict("action_id принадлежит другому Telegram-пользователю")
    if action.status != AttendanceAction.Status.SUCCEEDED:
        raise AttendanceTemporarilyUnavailable("операция ещё обрабатывается")
    reason = "action_id"
    if update_id is not None and action.update_id == update_id:
        reason = "update_id"
    elif (
        chat_id is not None
        and message_id is not None
        and action.chat_id == chat_id
        and action.message_id == message_id
    ):
        reason = "chat_id_message_id"
    logger.info(
        "attendance_action_duplicate",
        extra={
            "event": "attendance_action_duplicate",
            "action_id": str(action.action_id),
            "source": source,
            "teacher_id": teacher.id,
            "visit_id": action.visit_id,
            "result": action.result_code,
            "duplicate_reason": reason,
            "process_id": os.getpid(),
            "handler_name": "webapp_checkin_static",
            "update_id": update_id,
            "message_id": message_id,
            "chat_id": chat_id,
            "telegram_user_id": telegram_user_id,
            "correlation_id": action.correlation_id,
        },
    )
    return AttendanceResult(
        status=action.response_status,
        result_code=action.result_code,
        visit_id=action.visit_id,
        duplicate=True,
        duplicate_reason=reason,
    )


def apply_attendance_action(
    *,
    action_id,
    source,
    teacher,
    campus_name,
    telegram_user_id=None,
    update_id=None,
    message_id=None,
    chat_id=None,
    correlation_id="",
    instance_id="",
):
    existing = _existing_result(
        action_id=action_id,
        source=source,
        teacher=teacher,
        telegram_user_id=telegram_user_id,
        update_id=update_id,
        chat_id=chat_id,
        message_id=message_id,
    )
    if existing is not None:
        return existing

    try:
        with transaction.atomic():
            action = AttendanceAction.objects.create(
                action_id=action_id,
                source=source,
                teacher=teacher,
                telegram_user_id=telegram_user_id,
                update_id=update_id,
                message_id=message_id,
                chat_id=chat_id,
                correlation_id=correlation_id,
                status=AttendanceAction.Status.PROCESSING,
            )
            logger.info(
                "attendance_action_created",
                extra={
                    "event": "attendance_action_created",
                    "action_id": str(action.action_id),
                    "source": source,
                    "teacher_id": teacher.id,
                    "correlation_id": correlation_id,
                    "instance_id": instance_id,
                    "process_id": os.getpid(),
                    "handler_name": "webapp_checkin_static",
                    "update_id": update_id,
                    "message_id": message_id,
                    "chat_id": chat_id,
                    "telegram_user_id": telegram_user_id,
                },
            )

            now = timezone.localtime(timezone.now())
            today = now.date()
            visit = VisitLog.objects.filter(teacher=teacher, date=today).first()

            if visit is None:
                visit = VisitLog.objects.create(
                    teacher=teacher,
                    telegram_id=telegram_user_id,
                    date=today,
                    time_in=now.time(),
                    location=campus_name,
                )
                result_code = "CHECKED_IN"
                response_status = f"ВЫ ВОШЛИ СЕГОДНЯ. Корпус: {campus_name}"
                event_name = "attendance_checkin_success"
            elif visit.time_out is None:
                visit.time_out = now.time()
                if visit.time_in:
                    start_dt = datetime.combine(today, visit.time_in)
                    end_dt = datetime.combine(today, now.time())
                    visit.attendance = end_dt - start_dt
                visit.save(update_fields=["time_out", "attendance"])
                result_code = "CHECKED_OUT"
                response_status = f"ВЫ ВЫШЛИ СЕГОДНЯ. Корпус: {visit.location or campus_name}"
                event_name = "attendance_checkout_success"
            else:
                result_code = "ALREADY_COMPLETED"
                response_status = f"ВЫ УЖЕ ОТМЕТИЛИСЬ. Корпус: {visit.location or campus_name}"
                event_name = "attendance_action_already_completed"

            action.visit = visit
            action.result_code = result_code
            action.response_status = response_status
            action.status = AttendanceAction.Status.SUCCEEDED
            action.completed_at = timezone.now()
            action.save(
                update_fields=[
                    "visit",
                    "result_code",
                    "response_status",
                    "status",
                    "completed_at",
                ]
            )
            logger.info(
                event_name,
                extra={
                    "event": event_name,
                    "action_id": str(action.action_id),
                    "source": source,
                    "teacher_id": teacher.id,
                    "visit_id": visit.id,
                    "result": result_code,
                    "correlation_id": correlation_id,
                    "instance_id": instance_id,
                    "process_id": os.getpid(),
                    "handler_name": "webapp_checkin_static",
                    "update_id": update_id,
                    "message_id": message_id,
                    "chat_id": chat_id,
                    "telegram_user_id": telegram_user_id,
                },
            )
            return AttendanceResult(
                status=response_status,
                result_code=result_code,
                visit_id=visit.id,
                duplicate=False,
            )
    except IntegrityError as exc:
        try:
            existing = _existing_result(
                action_id=action_id,
                source=source,
                teacher=teacher,
                telegram_user_id=telegram_user_id,
                update_id=update_id,
                chat_id=chat_id,
                message_id=message_id,
            )
        except OperationalError as lookup_exc:
            raise AttendanceTemporarilyUnavailable(
                "база временно занята; повторите тот же action_id"
            ) from lookup_exc
        if existing is not None:
            return existing
        raise AttendanceTemporarilyUnavailable(
            "конкурирующая операция ещё фиксируется; повторите тот же action_id"
        ) from exc
    except OperationalError as exc:
        logger.warning(
            "attendance_operation_failed",
            extra={
                "event": "attendance_operation_failed",
                "action_id": str(action_id),
                "source": source,
                "teacher_id": teacher.id,
                "correlation_id": correlation_id,
                "instance_id": instance_id,
                "process_id": os.getpid(),
                "handler_name": "webapp_checkin_static",
                "update_id": update_id,
                "message_id": message_id,
                "chat_id": chat_id,
                "telegram_user_id": telegram_user_id,
                "reason": "database_operational_error",
            },
        )
        raise AttendanceTemporarilyUnavailable(
            "база временно занята; повторите тот же action_id"
        ) from exc
