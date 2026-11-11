"""Brute-force protection: temporary lock-outs per (account, IP) and per IP.

Hooked into the authentication backend, so it protects BOTH the normal login page
and the Django admin login. Counters live in the database (shared by all workers).
"""
import hashlib
import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import LoginAttempt

logger = logging.getLogger("security")


def client_ip(request):
    if request is None:
        return "unknown"
    if getattr(settings, "TRUST_X_FORWARDED_FOR", False):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded:
            # With ONE trusted reverse proxy, the last entry is the one the proxy appended.
            return forwarded.split(",")[-1].strip()[:45]
    return request.META.get("REMOTE_ADDR", "unknown")[:45]


def _keys(request, identifier):
    ip = client_ip(request)
    ident = hashlib.sha256((identifier or "").strip().lower().encode()).hexdigest()[:32]
    return [
        (f"u:{ident}|{ip}", settings.LOGIN_MAX_ATTEMPTS),       # one account from one address
        (f"ip:{ip}", settings.LOGIN_MAX_ATTEMPTS_PER_IP),       # password spraying from one address
    ]


def _window():
    return timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)


def is_locked(request, identifier):
    keys = [k for k, _ in _keys(request, identifier)]
    return LoginAttempt.objects.filter(key__in=keys, locked_until__gt=timezone.now()).exists()


def register_failure(request, identifier):
    now = timezone.now()
    for key, limit in _keys(request, identifier):
        with transaction.atomic():
            attempt, _ = LoginAttempt.objects.select_for_update().get_or_create(key=key)
            if attempt.locked_until and attempt.locked_until <= now:
                attempt.failures, attempt.locked_until = 0, None          # lock expired
            elif attempt.last_failure and now - attempt.last_failure > _window():
                attempt.failures = 0                                       # stale counter
            attempt.failures += 1
            attempt.last_failure = now
            if attempt.failures >= limit and not attempt.locked_until:
                attempt.locked_until = now + _window()
                logger.warning("Login lock-out triggered for %s", key.split("|")[-1])
            attempt.save()


def reset(request, identifier):
    """Successful login clears the account+IP counter (the IP-wide counter is kept)."""
    LoginAttempt.objects.filter(key=_keys(request, identifier)[0][0]).delete()
