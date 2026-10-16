import requests

url = "http://127.0.0.1:8000/api/webapp-checkin/"
payload = {
    "phone": "7712821636",  # последние 10 цифр
    "latitude": 53.2852,
    "longitude": 69.3922,
    "accuracy": 20,
    "userAgent": "telegram-android"
}

r = requests.post(url, json=payload)
print("Status:", r.status_code)
print("Response:", r.json())
