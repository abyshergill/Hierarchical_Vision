import time
from functools import wraps

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse

from .throttle import client_ip


def _current_minute():
    return int(time.time() // 60)


def rate_limit(scope):
    """Limit requests per minute per user (or per IP) - stops directory scraping."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            who = request.user.pk if request.user.is_authenticated else client_ip(request)
            key = f"rl:{scope}:{who}:{_current_minute()}"
            cache.add(key, 0, timeout=90)
            try:
                count = cache.incr(key)
            except ValueError:
                cache.set(key, 1, timeout=90)
                count = 1
            if count > getattr(settings, "RATE_LIMIT_PER_MINUTE", 120):
                return HttpResponse("Too many requests. Please slow down.", status=429)
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
