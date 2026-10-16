import hashlib
import hmac
import json

from django.conf import settings


SIGNED_FIELDS = (
    "source",
    "action_id",
    "update_id",
    "message_id",
    "chat_id",
    "telegram_user_id",
    "correlation_id",
    "instance_id",
)


def _key() -> bytes:
    value = getattr(settings, "ATTENDANCE_API_SIGNING_KEY", None) or settings.SECRET_KEY
    return value.encode("utf-8")


def canonical_attendance_payload(data: dict) -> bytes:
    selected = {key: data.get(key) for key in SIGNED_FIELDS}
    return json.dumps(
        selected,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def sign_attendance_payload(data: dict) -> str:
    return hmac.new(
        _key(),
        canonical_attendance_payload(data),
        hashlib.sha256,
    ).hexdigest()


def verify_attendance_signature(data: dict, signature: str | None) -> bool:
    if not signature:
        return False
    expected = sign_attendance_payload(data)
    return hmac.compare_digest(expected, signature)
