"""Django settings for Hierarchical Vision."""
import os
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path):
    """Tiny .env loader (KEY=VALUE per line) so no extra dependency is needed."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")

TESTING = "test" in sys.argv
DEBUG = os.environ.get("DEBUG", "1") == "1"  # set DEBUG=0 in production!
SECRET_KEY = os.environ.get("SECRET_KEY", "django-insecure-dev-only-change-me")
if not DEBUG and SECRET_KEY.startswith("django-insecure"):
    raise ImproperlyConfigured("Set a real SECRET_KEY when DEBUG is off.")

ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "leaves",
    "notifications",
    "newsletter",
    "support",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "config.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "notifications.context_processors.unread_notifications",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ----------------------------------------------------------------------------
# Database: SQLite for development (default), PostgreSQL when you are ready.
#   DB_ENGINE=sqlite    -> db.sqlite3 next to manage.py (nothing else to configure)
#   DB_ENGINE=postgres  -> DB_NAME / DB_USER / DB_PASSWORD / DB_HOST / DB_PORT
#   or a single DATABASE_URL=postgres://user:pass@host:5432/dbname
# See "Switching to PostgreSQL" in README.md.
# ----------------------------------------------------------------------------
def _database_from_env():
    from urllib.parse import unquote, urlparse

    url = os.environ.get("DATABASE_URL", "").strip()
    engine = os.environ.get("DB_ENGINE", "").strip().lower()
    cfg = {}
    if url:
        parsed = urlparse(url)
        if parsed.scheme in ("postgres", "postgresql", "pgsql"):
            engine = "postgres"
            cfg = {
                "NAME": unquote(parsed.path.lstrip("/")), "USER": unquote(parsed.username or ""),
                "PASSWORD": unquote(parsed.password or ""), "HOST": parsed.hostname or "localhost",
                "PORT": str(parsed.port or 5432),
            }
        elif parsed.scheme == "sqlite":
            engine = "sqlite"
        else:
            raise ImproperlyConfigured(f"Unsupported DATABASE_URL scheme: {parsed.scheme!r}")

    if engine in ("", "sqlite", "sqlite3"):
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / os.environ.get("SQLITE_NAME", "db.sqlite3")}
    if engine in ("postgres", "postgresql", "pg", "pgsql"):
        db = {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": cfg.get("NAME") or os.environ.get("DB_NAME", "hierarchical_vision"),
            "USER": cfg.get("USER") or os.environ.get("DB_USER", "postgres"),
            "PASSWORD": cfg.get("PASSWORD") or os.environ.get("DB_PASSWORD", ""),
            "HOST": cfg.get("HOST") or os.environ.get("DB_HOST", "localhost"),
            "PORT": cfg.get("PORT") or os.environ.get("DB_PORT", "5432"),
            "CONN_MAX_AGE": int(os.environ.get("DB_CONN_MAX_AGE", "60")),
        }
        sslmode = os.environ.get("DB_SSLMODE", "").strip()   # e.g. require, verify-full
        if sslmode:
            db["OPTIONS"] = {"sslmode": sslmode}
        return db
    raise ImproperlyConfigured(f"Unknown DB_ENGINE {engine!r}. Use 'sqlite' or 'postgres'.")


DATABASES = {"default": _database_from_env()}

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["accounts.backends.EmployeeIdOrEmailBackend"]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:home"
LOGOUT_REDIRECT_URL = "accounts:login"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Bangkok"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# E-mail notifications (console backend prints to the terminal by default).
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "25"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "0") == "1"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "hr@example.com")

# Leave-policy knobs
WORK_HOURS_PER_DAY = 8
WORKING_WEEKDAYS = (0, 1, 2, 3, 4)  # Monday=0 ... Sunday=6. Use (0..5) for a Mon-Sat week.
MAX_IMAGE_UPLOAD_MB = 20                  # JPG / JPEG / PNG only (see accounts/sanitize.py)
NEWSLETTER_MAX_IMAGES = 6                 # per post
NEWSLETTER_PAGE_SIZE = 8


# ----------------------------------------------------------------------------
# Security
# ----------------------------------------------------------------------------
ADMIN_URL = os.environ.get("ADMIN_URL", "django-admin/")       # change in production to hide the admin
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}  # use Redis with many workers
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "120"))

# Brute-force lock-out (see accounts/throttle.py)
LOGIN_MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS", "5"))               # per account + IP
LOGIN_MAX_ATTEMPTS_PER_IP = int(os.environ.get("LOGIN_MAX_ATTEMPTS_PER_IP", "30"))  # password spraying
LOGIN_LOCKOUT_MINUTES = int(os.environ.get("LOGIN_LOCKOUT_MINUTES", "15"))
TRUST_X_FORWARDED_FOR = os.environ.get("TRUST_X_FORWARDED_FOR", "0") == "1"  # only behind ONE trusted proxy

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 8          # 8 hours
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False               # keep False: forms read the token from the cookie/template
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024   # larger uploads are streamed to a temp file, not held in RAM
FILE_UPLOAD_PERMISSIONS = 0o640
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o750
DATA_UPLOAD_MAX_NUMBER_FIELDS = 600   # per-day leave rows + newsletter forms

if not DEBUG and not TESTING:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "1") == "1"
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    if os.environ.get("BEHIND_PROXY", "0") == "1":
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
