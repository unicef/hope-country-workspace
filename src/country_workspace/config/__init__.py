from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, Optional, TypeAlias, Union

from smart_env import SmartEnv

if TYPE_CHECKING:
    ConfigItem: TypeAlias = Union[
        tuple[type, Any, Any, bool, str],
        tuple[type, Optional[Any], Optional[Any], bool],
        tuple[type, Any, Any],
        tuple[type, Any],
    ]

DJANGO_HELP_BASE = "https://docs.djangoproject.com/en/5.0/ref/settings"


def setting(anchor: str) -> str:
    return f"@see {DJANGO_HELP_BASE}#{anchor}"


def celery_doc(anchor: str) -> str:
    return f"@see https://docs.celeryq.dev/en/stable/" f"userguide/configuration.html#{anchor}"


class Group(Enum):
    DJANGO = 1


CONFIG: "Dict[str, ConfigItem]" = {
    "SUPERUSERS": (
        list,
        [],
        [],
        False,
        "list of emails that will automatically created as superusers",
    ),
    "ADMIN_EMAIL": (str, "", "admin", True, "Initial user created at first deploy"),
    "ADMIN_PASSWORD": (
        str,
        "",
        "",
        True,
        "Password for initial user created at first deploy",
    ),
    "ALLOWED_HOSTS": (
        list,
        [],
        ["127.0.0.1", "localhost"],
        True,
        setting("allowed-hosts"),
    ),
    "AUTHENTICATION_BACKENDS": (
        list,
        [],
        [],
        False,
        setting("authentication-backends"),
    ),
    "CACHE_URL": (str, "", "redis://localhost:6379/0", True, setting("cache-url")),
    "CELERY_BROKER_URL": (
        str,
        "",
        "",
        True,
        "https://docs.celeryq.dev/en/stable/django/first-steps-with-django.html",
    ),
    "CELERY_TASK_ALWAYS_EAGER": (
        bool,
        False,
        True,
        False,
        f"{celery_doc}#std-setting-task_always_eager",
    ),
    "CELERY_TASK_EAGER_PROPAGATES": (
        bool,
        True,
        True,
        False,
        f"{celery_doc}#task-eager-propagates",
    ),
    "CELERY_VISIBILITY_TIMEOUT": (
        int,
        1800,
        1800,
        False,
        f"{celery_doc}#broker-transport-options",
    ),
    "CSRF_COOKIE_SECURE": (bool, True, False, True, setting("csrf-cookie-secure")),
    "CSRF_TRUSTED_ORIGINS": (list, "localhost", "", True, ""),
    "DATABASE_URL": (
        str,
        SmartEnv.NOTSET,
        SmartEnv.NOTSET,
        True,
        "https://django-environ.readthedocs.io/en/latest/types.html#environ-env-db-url",
    ),
    "DEBUG": (bool, False, True, False, setting("debug")),
    # "EMAIL_BACKEND": (
    #     str,
    #     "django.core.mail.backends.smtp.EmailBackend",
    #     setting("email-backend"),
    #     True,
    # ),
    "EMAIL_HOST": (str, "", "", False, setting("email-host")),
    "EMAIL_HOST_USER": (str, "", "", False, setting("email-host-user")),
    "EMAIL_HOST_PASSWORD": (str, "", "", False, setting("email-host-password")),
    "EMAIL_PORT": (int, "25", "25", False, setting("email-port")),
    "EMAIL_SUBJECT_PREFIX": (
        str,
        "[Hope-cw]",
        "[Hope-ce]",
        False,
        setting("email-subject-prefix"),
    ),
    "EMAIL_USE_LOCALTIME": (
        bool,
        False,
        False,
        False,
        setting("email-use-localtime"),
    ),
    "EMAIL_USE_TLS": (bool, False, False, False, setting("email-use-tls")),
    "EMAIL_USE_SSL": (bool, False, False, False, setting("email-use-ssl")),
    "EMAIL_TIMEOUT": (str, None, None, False, setting("email-timeout")),
    "LOGGING_LEVEL": (str, "CRITICAL", "DEBUG", False, setting("logging-level")),
    "FILE_STORAGE_DEFAULT": (
        str,
        "django.core.files.storage.FileSystemStorage",
        setting("storages"),
    ),
    "FILE_STORAGE_MEDIA": (
        str,
        "django.core.files.storage.FileSystemStorage",
        setting("storages"),
    ),
    "FILE_STORAGE_STATIC": (
        str,
        "django.contrib.staticfiles.storage.StaticFilesStorage",
        setting("storages"),
    ),
    "HOPE_API_TOKEN": (str, "", "", True, "Hope API token"),
    "MEDIA_ROOT": (str, "/var/media/", "/tmp/media", True, setting("media-root")),  # nosec
    "MEDIA_URL": (str, "/media/", "/media", False, setting("media-root")),  # nosec
    # "ROOT_TOKEN": (str, "", ""),
    "SECRET_KEY": (
        str,
        "",
        "super_secret_key_just_for_testing",
        True,
        setting("secret-key"),
    ),
    "ROOT_TOKEN_HEADER": (str, "x-root-token", "x-root-token"),
    "ROOT_TOKEN": (str, "", ""),
    # "SECURE_HSTS_PRELOAD": (bool, True, setting("secure-hsts-preload"), False),
    # "SECURE_HSTS_SECONDS": (int, 60, setting("secure-hsts-seconds")),
    # "SECURE_SSL_REDIRECT": (bool, True, setting("secure-ssl-redirect"), False),
    "SENTRY_DSN": (str, "", "", False, "Sentry DSN"),
    "SENTRY_ENVIRONMENT": (str, "production", "develop", False, "Sentry Environment"),
    "SENTRY_URL": (str, "", "", False, "Sentry server url"),
    # "SESSION_COOKIE_DOMAIN": (
    #     str,
    #     "",
    #     setting("std-setting-SESSION_COOKIE_DOMAIN"),
    #     "localhost",
    # ),
    # "SESSION_COOKIE_HTTPONLY": (bool, True, setting("session-cookie-httponly"), False),
    # "SESSION_COOKIE_NAME": (str, "dedupe_session", setting("session-cookie-name")),
    # "SESSION_COOKIE_PATH": (str, "/", setting("session-cookie-path")),
    # "SESSION_COOKIE_SECURE": (bool, True, setting("session-cookie-secure"), False),
    # "SIGNING_BACKEND": (
    #     str,
    #     "django.core.signing.TimestampSigner",
    #     setting("signing-backend"),
    # ),
    "SOCIAL_AUTH_LOGIN_URL": (str, "/login/", "", False, ""),
    "SOCIAL_AUTH_RAISE_EXCEPTIONS": (bool, False, True, False),
    "SOCIAL_AUTH_REDIRECT_IS_HTTPS": (bool, True, False, False, ""),
    # "STATIC_FILE_STORAGE": (
    #     str,
    #     "django.core.files.storage.FileSystemStorage",
    #     setting("storages"),
    # ),
    "STATIC_ROOT": (str, "/var/static", "/tmp/static", True, setting("static-root")),  # nosec
    "STATIC_URL": (str, "/static/", "/static/", False, setting("static-url")),  # nosec
    "TIME_ZONE": (str, "UTC", "UTC", False, setting("std-setting-TIME_ZONE")),
    # "AZURE_ACCOUNT_NAME": (str, ""),
    # "AZURE_ACCOUNT_KEY": (str, ""),
    # "AZURE_CUSTOM_DOMAIN": (str, ""),
    # "AZURE_CONNECTION_STRING": (str, ""),
    # "CV2DNN_PATH": (str, ""),
}

env = SmartEnv(**CONFIG)
