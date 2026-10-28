"""Django settings. Everything environment-specific comes from environment variables; business
settings live in config/*.yaml (msd.conf)."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from django.utils.csp import CSP

BASE_DIR = Path(__file__).resolve().parent
ENV = os.environ.get("MSD_ENV", "dev")
DEBUG = os.environ.get("MSD_DEBUG", "1" if ENV == "dev" else "0") == "1"
SECRET_KEY = os.environ.get("MSD_SECRET_KEY", "dev-only-secret-key-change-me-0123456789abcdef" if ENV != "prod" else "")
if ENV == "prod" and len(SECRET_KEY) < 50:
    raise RuntimeError("MSD_SECRET_KEY must be set (50+ characters) in production")
ALLOWED_HOSTS = [h for h in os.environ.get("MSD_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",") if h]
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("MSD_CSRF_TRUSTED_ORIGINS", "").split(",") if o]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_tasks_db",
    "msd.tenancy",
    "msd.connectors",
    "msd.metrics",
    "msd.analysis",
    "msd.assistant",
    "msd.proposals",
    "msd.web",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
]

ROOT_URLCONF = "msd.urls"
WSGI_APPLICATION = "msd.wsgi.application"
ASGI_APPLICATION = "msd.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.csp",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "msd.web.context.ui",
            ],
        },
    }
]


def _database() -> dict:
    url = urlparse(os.environ.get("DATABASE_URL", "postgresql://msd:msd@127.0.0.1:5432/msd"))
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": url.path.lstrip("/"),
        "USER": unquote(url.username or ""),
        "PASSWORD": unquote(url.password or ""),
        "HOST": url.hostname or "",
        "PORT": str(url.port or 5432),
        "CONN_MAX_AGE": 0,  # row-level security context is per transaction; never reuse a session's state
        "TEST": {"NAME": os.environ.get("MSD_TEST_DB", "msd_test")},
    }


DATABASES = {"default": _database()}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

TASKS = {
    "default": {
        "BACKEND": os.environ.get("MSD_TASK_BACKEND", "django.tasks.backends.immediate.ImmediateBackend" if ENV != "prod" else "django_tasks_db.DatabaseBackend"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Europe/Berlin"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = Path(os.environ.get("MSD_STATIC_ROOT", BASE_DIR.parents[1] / "staticfiles"))
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage" if ENV == "prod" else "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Content Security Policy (Django 6): no inline script or style, no eval. Alpine runs from its CSP
# build and HTMX with eval switched off, so the policy needs no exceptions.
SECURE_CSP = {
    "default-src": [CSP.SELF],
    "script-src": [CSP.SELF, CSP.NONCE],
    "style-src": [CSP.SELF],
    "img-src": [CSP.SELF, "data:"],
    "connect-src": [CSP.SELF],
    "font-src": [CSP.SELF],
    "frame-ancestors": [CSP.NONE],
    "form-action": [CSP.SELF],
    "base-uri": [CSP.NONE],
    "object-src": [CSP.NONE],
}
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
if ENV == "prod":
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = os.environ.get("MSD_SSL_REDIRECT", "1") == "1"
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = 31536000

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": os.environ.get("MSD_LOG_LEVEL", "INFO")},
    "loggers": {"httpx": {"level": "WARNING"}, "django.tasks": {"level": "WARNING"}},
}
