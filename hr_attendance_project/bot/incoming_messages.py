import requests

from bot.config import BOT_TOKEN


TELEGRAM_SEND_MESSAGE_URL = (
    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
)


def send_telegram_notification(chat_id: int, text: str) -> dict:
    try:
        response = requests.post(TELEGRAM_SEND_MESSAGE_URL,json={"chat_id": int(chat_id),"text": text},timeout=15)

        result = response.json()

        if not response.ok or not result.get("ok"):
            return {"success": False, "error": result.get("description","Неизвестная ошибка Telegram")}

        return {"success": True, "message_id": result["result"]["message_id"]}

    except requests.RequestException as error:
        return {"success": False, "error": str(error)}