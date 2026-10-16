import json
import threading
import uuid
from unittest.mock import AsyncMock, Mock, patch

from django.db import OperationalError, close_old_connections
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase

from bot.handlers import _reply_with_result, cmd_start, handle_location
from myapp.models import AttendanceAction, Campus, Teacher, VisitLog
from myapp.services.attendance import AttendanceTemporarilyUnavailable, apply_attendance_action
from myapp.utils.attendance_signing import sign_attendance_payload


class AttendanceEndpointMixin:
    url = "/api/webapp-checkin-static/"

    def setUp(self):
        self.campus = Campus.objects.create(name="korpus-test", latitude=51.0, longitude=71.0, radius=150)
        self.teacher = Teacher.objects.create(
            fio="Test One", job_title="Teacher", phone="+77000000001", telegram_id=101
        )

    def payload(self, *, action_id=None, teacher=None, **overrides):
        teacher = teacher or self.teacher
        data = {
            "source": "telegram_webapp",
            "action_id": str(action_id or uuid.uuid4()),
            "phone": teacher.phone_clean,
            "telegram_id": teacher.telegram_id,
            "latitude": self.campus.latitude,
            "longitude": self.campus.longitude,
            "accuracy": 10,
            "userAgent": "test-client",
            "location": self.campus.name,
        }
        data.update(overrides)
        return data

    def post(self, payload, *, url=None, signed=False):
        headers = {}
        if signed:
            headers["HTTP_X_ATTENDANCE_SIGNATURE"] = sign_attendance_payload(payload)
        return self.client.post(
            url or self.url, data=json.dumps(payload), content_type="application/json", **headers
        )


class AttendanceIdempotencyTests(AttendanceEndpointMixin, TestCase):
    def test_one_action_creates_one_checkin_and_duplicate_returns_saved_result(self):
        payload = self.payload(action_id=uuid.uuid4())
        first, second = self.post(payload), self.post(payload)
        self.assertEqual(first.json()["result"], "CHECKED_IN")
        self.assertFalse(first.json()["duplicate"])
        self.assertTrue(second.json()["duplicate"])
        self.assertEqual(second.json()["result"], "CHECKED_IN")
        self.assertEqual(VisitLog.objects.count(), 1)
        self.assertIsNone(VisitLog.objects.get().time_out)

    def test_repeated_update_id_is_deduplicated_with_new_action_id(self):
        base = self.payload(source="telegram_bot", update_id=9001, message_id=22, chat_id=33, telegram_user_id=101)
        self.assertEqual(self.post(base, url="/webapp/", signed=True).status_code, 200)
        repeated = {**base, "action_id": str(uuid.uuid4())}
        second = self.post(repeated, url="/webapp/", signed=True)
        self.assertTrue(second.json()["duplicate"])
        self.assertEqual(second.json()["duplicate_reason"], "update_id")
        self.assertIsNone(VisitLog.objects.get().time_out)

    def test_repeated_message_in_same_chat_is_deduplicated(self):
        base = self.payload(source="telegram_bot", update_id=9101, message_id=23, chat_id=34, telegram_user_id=101)
        self.post(base, url="/webapp/", signed=True)
        repeated = {**base, "action_id": str(uuid.uuid4()), "update_id": 9102}
        result = self.post(repeated, url="/webapp/", signed=True)
        self.assertTrue(result.json()["duplicate"])
        self.assertEqual(result.json()["duplicate_reason"], "chat_id_message_id")
        self.assertIsNone(VisitLog.objects.get().time_out)

    def test_two_users_are_independent(self):
        other = Teacher.objects.create(fio="Test Two", job_title="Teacher", phone="+77000000002", telegram_id=102)
        self.assertEqual(self.post(self.payload()).json()["result"], "CHECKED_IN")
        self.assertEqual(self.post(self.payload(teacher=other)).json()["result"], "CHECKED_IN")
        self.assertEqual(VisitLog.objects.count(), 2)

    def test_new_action_after_checkin_checks_out(self):
        self.assertEqual(self.post(self.payload()).json()["result"], "CHECKED_IN")
        self.assertEqual(self.post(self.payload()).json()["result"], "CHECKED_OUT")
        self.assertIsNotNone(VisitLog.objects.get().time_out)

    def test_old_action_after_new_action_does_not_toggle_again(self):
        old = self.payload()
        self.post(old)
        self.post(self.payload())
        before = VisitLog.objects.get().time_out
        repeated = self.post(old)
        self.assertTrue(repeated.json()["duplicate"])
        self.assertEqual(repeated.json()["result"], "CHECKED_IN")
        self.assertEqual(VisitLog.objects.get().time_out, before)

    def test_lost_http_response_can_be_retried_safely(self):
        payload = self.payload()
        self.post(payload)
        retry = self.post(payload)
        self.assertTrue(retry.json()["duplicate"])
        self.assertEqual(retry.json()["result"], "CHECKED_IN")
        self.assertIsNone(VisitLog.objects.get().time_out)

    def test_bot_endpoint_rejects_unsigned_source_claim(self):
        payload = self.payload(source="telegram_bot", update_id=1, message_id=2, chat_id=3, telegram_user_id=101)
        self.assertEqual(self.post(payload, url="/webapp/").status_code, 403)
        self.assertEqual(VisitLog.objects.count(), 0)

    def test_action_cannot_be_reused_by_another_user(self):
        action_id = uuid.uuid4()
        self.post(self.payload(action_id=action_id))
        other = Teacher.objects.create(fio="Test Two", job_title="Teacher", phone="+77000000002", telegram_id=102)
        response = self.post(self.payload(action_id=action_id, teacher=other))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(VisitLog.objects.count(), 1)

    def test_database_error_rolls_back_action_and_allows_retry(self):
        action_id = uuid.uuid4()
        with patch("myapp.services.attendance.VisitLog.objects.create", side_effect=OperationalError("locked")):
            with self.assertRaises(AttendanceTemporarilyUnavailable):
                apply_attendance_action(action_id=action_id, source="telegram_webapp", teacher=self.teacher, campus_name=self.campus.name)
        self.assertFalse(AttendanceAction.objects.filter(action_id=action_id).exists())
        result = apply_attendance_action(action_id=action_id, source="telegram_webapp", teacher=self.teacher, campus_name=self.campus.name)
        self.assertEqual(result.result_code, "CHECKED_IN")


class ConcurrentAttendanceTests(AttendanceEndpointMixin, TransactionTestCase):
    reset_sequences = True

    def test_two_simultaneous_requests_change_visit_at_most_once(self):
        payload = self.payload()
        barrier, responses = threading.Barrier(2), []

        def worker():
            close_old_connections()
            client = Client()
            barrier.wait()
            response = client.post(self.url, data=json.dumps(payload), content_type="application/json")
            responses.append(response.status_code)
            close_old_connections()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        retry = self.post(payload)
        self.assertEqual(retry.status_code, 200)
        self.assertTrue(retry.json()["duplicate"])
        self.assertEqual(VisitLog.objects.count(), 1)
        self.assertIsNone(VisitLog.objects.get().time_out)
        self.assertIn(200, responses)


class BotReplyTests(SimpleTestCase):
    async def test_success_is_one_message_and_removes_keyboard_without_dot(self):
        message = Mock()
        message.answer = AsyncMock()
        success = await _reply_with_result(message, 200, {"status": "ВЫ ВОШЛИ СЕГОДНЯ. Корпус: test"})
        self.assertTrue(success)
        message.answer.assert_awaited_once()
        args, kwargs = message.answer.await_args
        self.assertNotEqual(args[0], ".")
        self.assertTrue(kwargs["reply_markup"].remove_keyboard)

    async def test_start_creates_a_new_user_bound_action(self):
        message = Mock()
        message.text = "/start static_korpus-1"
        message.from_user.id = 101
        message.answer = AsyncMock()
        state = Mock()
        state.clear = AsyncMock()
        state.update_data = AsyncMock()
        await cmd_start(message, state)
        state.clear.assert_awaited_once()
        kwargs = state.update_data.await_args.kwargs
        uuid.UUID(kwargs["action_id"])
        uuid.UUID(kwargs["correlation_id"])
        self.assertEqual(kwargs["action_owner"], 101)

    async def test_missing_fsm_state_refuses_location_without_http(self):
        message = Mock()
        message.from_user.id = 101
        message.chat.id = 33
        message.message_id = 22
        message.location.horizontal_accuracy = 10
        message.answer = AsyncMock()
        state = Mock()
        state.get_data = AsyncMock(return_value={})
        update = Mock(update_id=9001)
        with patch("bot.handlers._send_attendance", new=AsyncMock()) as sender:
            await handle_location(message, state, update)
        sender.assert_not_awaited()
        message.answer.assert_awaited_once()
        self.assertIn("/start", message.answer.await_args.args[0])
