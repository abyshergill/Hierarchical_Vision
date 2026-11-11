from django.conf import settings
from django.utils.cache import patch_cache_control

CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",   # inline style="" attributes are used for colours/progress bars
    "img-src 'self' data:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


class SecurityHeadersMiddleware:
    """CSP, Permissions-Policy and no-store caching for authenticated pages."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        path = request.path
        if not path.startswith(f"/{settings.ADMIN_URL}"):  # Django admin ships its own inline assets
            response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if path.startswith("/static/"):
            return response
        if path.startswith("/media/"):
            patch_cache_control(response, private=True, max_age=3600)
        elif request.user.is_authenticated:
            patch_cache_control(response, private=True, no_store=True)
        return response
