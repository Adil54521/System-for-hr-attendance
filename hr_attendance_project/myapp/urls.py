from django.urls import path
from myapp import views
from .views import *
from myapp.models import *
from myapp.views import qr_secure
from myapp import views_static_qr
from myapp import count_abiturients

print("Загрузка MYAPP URLS работает!")

urlpatterns = [
    path('reports-center/', views.admin_panel, name='admin_panel'),
    path('reports-center/export/', export_excel, name='export_excel'),
    path("qr_redirect/", views.redirect_to_bot, name="redirect_to_bot"),
    #path("api/webapp-checkin/", views.webapp_checkin, name="webapp_checkin"),
    path("api/webapp-checkin-static/", views_static_qr.webapp_checkin_static, name="webapp_checkin_static"),
    path("webapp/", views_static_qr.webapp_checkin_static, name="webapp_checkin_static"),
    #path("qr-secure/<str:location>/", views.qr_handler, name="qr_handler"),
    #path("api/delete_button/", views.delete_button, name="delete_button"),
    path("qr-secure/<str:location>/", views.qr_secure, name="qr_secure"),
    path("qr-static/static-korpus-1/", views_static_qr.qr_static, name="qr_static"),
    path("test-headers/", test_headers),
    path("qr-abiturients/", count_abiturients.qr_make, name="qr_make"),
    path("qr-abiturients-status/", count_abiturients.check_ip, name="check_ip"),
    path("fetch/", views.fetch, name="fetch"),
    path("test/", views_static_qr.test_page, name="test"),
    path("message-read-statuses/", views_static_qr.message_read_statuses, name="message_read_statuses"),
    path("conversation-history/<int:recipient_id>/",views_static_qr.conversation_history,name="conversation_history"),
]