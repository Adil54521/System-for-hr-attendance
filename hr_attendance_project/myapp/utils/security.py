import hmac
import hashlib
import base64
import json
import os
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', 'key.env'))

QR_SECRET_KEY = os.getenv("QR_SECRET_KEY")

if not QR_SECRET_KEY:
    raise ValueError("❌ QR_SECRET_KEY не найден в key.env!")

def generate_signed_payload(data: dict) -> tuple[str, str]:
    payload_json = json.dumps(data, separators=(',', ':'))
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode()
    signature = hmac.new(
        QR_SECRET_KEY.encode(),
        payload_b64.encode(),
        hashlib.sha256
    ).hexdigest()
    return payload_b64, signature

def verify_signature(payload_b64: str, signature: str) -> dict | None:
    expected_sig = hmac.new(
        QR_SECRET_KEY.encode(),
        payload_b64.encode(),
        hashlib.sha256
    ).hexdigest()
    if hmac.compare_digest(expected_sig, signature):
        try:
            payload_json = base64.urlsafe_b64decode(payload_b64).decode()
            return json.loads(payload_json)
        except Exception:
            return None
    return None
