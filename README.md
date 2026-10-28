# HR Attendance Bot

Telegram-based attendance system built with Django and aiogram.

Employees start an attendance session, share their location, and the system automatically records check-in or check-out based on their current attendance status.

## Features

- Telegram bot attendance flow: `/start` → share location → automatic check-in/check-out.
- Campus geofence validation.
- GPS accuracy validation.
- Employee identification through Telegram account or phone contact.
- Idempotent attendance actions: repeated Telegram updates or HTTP requests cannot create an unintended check-out.
- Redis-backed FSM storage and event isolation.
- Redis singleton lease to prevent two polling instances of the same bot.
- Structured rotating JSON logs.
- Django admin and attendance reports.

## Requirements

- Python 3.11+
- SQLite
- Redis
- Telegram Bot Token

## Installation

```bash
git clone <YOUR_REPOSITORY_URL>
cd hr_attendance_project


python -m venv venv
Activate the virtual environment:
# Windows
venv\Scripts\activate


# Linux/macOS
source venv/bin/activate
Install dependencies:
pip install -r requirements.txt
Configuration
Create a key.env file in the project root:
SECRET_KEY=your-django-secret-key
BOT_TOKEN=your-telegram-bot-token


# Use a separate random secret in production.
ATTENDANCE_API_SIGNING_KEY=your-attendance-api-signing-key


# Redis is required for bot FSM, event isolation, and polling lease.
REDIS_URL=redis://127.0.0.1:6379/2


# URL used by the bot to send attendance requests to Django.
ATTENDANCE_API_URL=https://your-domain.example/webapp/
Do not commit key.env, db.sqlite3, logs, or Bot Tokens to Git.
Database Setup

Run migrations:
python manage.py migrate

Create an administrator account:
python manage.py createsuperuser

Run the Django server:
python manage.py runserver

Open the admin panel:
http://127.0.0.1:8000/x29GJk/

Before using the bot, create campuses and employees in Django admin.

Run Redis
Example for a local Redis installation:
redis-server
Verify that Redis is reachable:
redis-cli ping
Expected output:
PONG

Run the Telegram Bot
Start Django first, then run the bot in another terminal:
python bot/main.py

Only one bot polling instance may run for the same Telegram token. The application uses a Redis lease to prevent accidental duplicate polling.

Attendance Flow
1. The employee sends /start.
2. The bot creates a unique attendance action_id.
3. The employee taps Send location.
4. The system validates GPS accuracy and campus geofence.
5. Django atomically records either:
   - check-in, if there is no open attendance record;
   - check-out, if an open record exists.
6. Repeating the same Telegram update, message, or action_id returns the already saved result and does not toggle attendance again.

Security Notes
- Bot-to-Django attendance requests are signed with HMAC.
- Keep ATTENDANCE_API_SIGNING_KEY secret and identical for Django and the bot.
- Rotate the Telegram Bot Token if it was ever exposed in logs, code, screenshots, or chat history.
- Fake GPS applications cannot always be reliably detected by a server if they provide plausible coordinates. The system currently validates GPS accuracy and campus radius; it does not guarantee detection of all location spoofing tools.
Logs

Attendance diagnostics are written as JSON lines:
logs/attendance.jsonl
Useful events include:
- telegram_update_received
- location_handler_started
- django_request_started
- django_request_finished
- attendance_action_created
- attendance_action_duplicate
- attendance_checkin_success
- attendance_checkout_success
- attendance_operation_failed

Tests
Run the test suite using an isolated Django test database:
python manage.py test myapp.tests

The tests cover idempotency, duplicate Telegram updates, duplicate messages, concurrent requests, retries after lost HTTP responses, WebApp duplicates, FSM-state loss, and check-in/check-out flow.

Production Checklist
- Configure HTTPS.
- Configure Redis as a persistent service.
- Set secure environment variables.
- Apply migrations:
python manage.py migrate
- Set DEBUG=False.
- Configure ALLOWED_HOSTS.
- Run Django through a production server such as Gunicorn, uWSGI, or Waitress.
- Run the Telegram bot as a supervised service.
- Back up db.sqlite3 regularly, or migrate to PostgreSQL for higher concurrency and production-scale usage.
