"""
WSGI config for hr_attendance_project project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os
from django.core.wsgi import get_wsgi_application
from werkzeug.middleware.proxy_fix import ProxyFix  # ✅ добавляем

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hr_attendance_project.settings')

application = get_wsgi_application()
application = ProxyFix(application, x_for=1, x_proto=1)
