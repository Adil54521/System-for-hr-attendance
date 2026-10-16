from django.http import HttpResponseForbidden

class BlockAdminPathMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Блокируем любой доступ к /admin/
        if request.path == "/admin/":
            return HttpResponseForbidden("403 Forbidden")
        return self.get_response(request)