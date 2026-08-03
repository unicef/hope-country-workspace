from enum import Enum
from typing import TYPE_CHECKING, Any

from smart_env import SmartEnv

if TYPE_CHECKING:
    ConfigItem: type = (
        tuple[type, Any, Any, bool, str]
        | tuple[type, Any | None, Any | None, bool]
        | tuple[type, Any, Any]
        | tuple[type, Any]
    )

DJANGO_HELP_BASE = "https://docs.djangoproject.com/en/5.0/ref/settings"


def setting(anchor: str) -> str:
    return f"@see {DJANGO_HELP_BASE}#{anchor}"


def celery_doc(anchor: str) -> str:
    return f"@see https://docs.celeryq.dev/en/stable/userguide/configuration.html#{anchor}"


class Group(Enum):
    DJANGO = 1


CONFIG: "dict[str, ConfigItem]" = {
    "SUPERUSERS": (
        list,
        [],
        [],
        False,
        """"list of emails/or usernames that will automatically granted superusers privileges
 ONLY the first time they are created. This is designed to be used in dev/qa environments deployed by CI,
 where database can be empty.
        """,
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
    "AURORA_API_TOKEN": (str, "", "", False, "Aurora API token"),
    "AURORA_API_URL": (str, "", "", False, "Aurora API url"),
    "CACHE_URL": (str, "redis://localhost:6379/0", "", True, setting("cache-url")),
    "SELECT2_CACHE": (
        str,
        "",
        "redis://localhost:6379/9",
        False,
        "https://django-select2.readthedocs.io/en/latest/django_select2.html#module-django_select2.conf",
    ),
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
        celery_doc("#std-setting-task_always_eager"),
    ),
    "CELERY_TASK_STORE_EAGER_RESULT": (
        bool,
        False,
        True,
        False,
        celery_doc("#std-setting-task_store_eager_result"),
    ),
    "CELERY_TASK_EAGER_PROPAGATES": (
        bool,
        True,
        True,
        False,
        celery_doc("#task-eager-propagates"),
    ),
    "CELERY_VISIBILITY_TIMEOUT": (
        int,
        1800,
        1800,
        False,
        celery_doc("#broker-transport-options"),
    ),
    "CSRF_COOKIE_SECURE": (bool, True, False, True, setting("csrf-cookie-secure")),
    "CSRF_TRUSTED_ORIGINS": (list, ["http://localhost"], "", True, ""),
    "DATABASE_URL": (
        str,
        SmartEnv.NOTSET,
        SmartEnv.NOTSET,
        True,
        "https://django-environ.readthedocs.io/en/latest/types.html#environ-env-db-url",
    ),
    "DEBUG": (bool, False, True, False, setting("debug")),
    "ENVIRONMENT": (str, "production", "develop", False, "Environment"),
    "EXTRA_APPS": (list, "", "", False, ""),  # nosec
    "EXTRA_AUTHENTICATION_BACKENDS": (
        list,
        [],
        [],
        False,
        "Extra authentications backends enabled to add. Es. `country_workspace.security.backends.AnyUserAuthBackend`",
    ),
    "EXTRA_MIDDLEWARES": (list, "", "", False, ""),  # nosec
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
    "FILE_STORAGE_HOPE": (
        str,
        "django.core.files.storage.FileSystemStorage",
        setting("storages"),
    ),
    "HOPE_API_URL": (
        str,
        "https://hope.unicef.org/api/rest/",
        "https://hope.unicef.org/api/rest/",
        False,
        "Hope API token",
    ),
    "HOPE_API_TOKEN": (str, "", "", False, "Hope API token"),
    "MEDIA_ROOT": (str, "/var/media/", "/tmp/media", True, setting("media-root")),  # noqa: S108
    "MEDIA_URL": (str, "/media/", "/media", False, setting("media-root")),
    "SECRET_KEY": (
        str,
        "",
        "super_secret_key_just_for_testing",
        True,
        setting("secret-key"),
    ),
    "ROOT_TOKEN_HEADER": (str, "x-root-token", "x-root-token"),
    "ROOT_TOKEN": (str, "", ""),
    "SENTRY_DSN": (str, "", "", False, "Sentry DSN"),
    "SENTRY_URL": (str, "", "", False, "Sentry server url"),
    "SENTRY_ENVIRONMENT": (str, ""),
    "SOCIAL_AUTH_LOGIN_URL": (str, "/login/", "", False, ""),
    "SOCIAL_AUTH_RAISE_EXCEPTIONS": (bool, False, True, False),
    "SOCIAL_AUTH_REDIRECT_IS_HTTPS": (bool, True, False, False, ""),
    "STATIC_ROOT": (str, "/var/static", "/tmp/static", True, setting("static-root")),  # noqa: S108
    "STATIC_URL": (str, "/static/", "/static/", False, setting("static-url")),
    "TIME_ZONE": (str, "UTC", "UTC", False, setting("std-setting-TIME_ZONE")),
    "AZURE_CLIENT_SECRET": (str, "", "", False, "Azure client secret for SSO"),
    "AZURE_TENANT_ID": (str, "", "", False, "Azure tenant ID for SSO"),
    "AZURE_CLIENT_ID": (str, "", "", False, "Azure client key for SSO"),
    "KOBO_KF_URL": (str, "", "", False, "Kobo API base URL"),
    "KOBO_MASTER_API_TOKEN": (str, "", "", False, "Kobo API master token"),
    "KOBO_PROJECT_VIEW_ID": (str, "", "", False, "Kobo project view ID"),
    "KOBO_API_TOKEN": (str, "", "", False, "Kobo API token"),
    "MAILJET_API_URL": (
        str,
        "https://api.mailjet.com/v3.1/",
        "https://api.mailjet.com/v3.1/",
        False,
        "Mailjet API URL",
    ),
    "MAILJET_API_KEY": (str, "", "", False, "Mailjet API key"),
    "MAILJET_SECRET_KEY": (str, "", "", False, "Mailjet API secret key"),
    "DEDUP_API_URL": (str, "", "", False, "Dedup Engine API base URL"),
    "DEDUP_API_TOKEN": (str, "", "", False, "Dedup Engine API token"),
    "APP_BASE_URL": (str, "", "", False, "Base URL of this application (used to build absolute callback URLs)"),
    "EMAIL_BACKEND": (
        str,
        "anymail.backends.mailjet.EmailBackend",
        "anymail.backends.mailjet.EmailBackend",
        False,
        "Email Backend",
    ),
    "DEFAULT_FROM_EMAIL": (
        str,
        "hope-workspace@mail.unicef.org",
        "hope-workspace@mail.unicef.org",
        False,
        "Default sending email address",
    ),
    "IGNORE_RECIPIENT_STATUS": (bool, False, True),
    "IGNORE_UNSUPPORTED_FEATURES": (bool, False, True),
    "REQUESTS_TIMEOUT": (int, 30, 30),
    "DEBUG_API_REQUESTS": (bool, False, False),
    "BITCASTER_API_URL": (str, "", "", False, "Bitcaster API URL"),
    "BITCASTER_ENABLED": (bool, False, False, False, "Enable Bitcaster notifications"),
    "BITCASTER_API_KEY": (str, "", "", False, "Bitcaster API key"),
    "BITCASTER_ORGANIZATION_SLUG": (str, "unicef", "unicef", False, "Bitcaster organization slug"),
    "BITCASTER_PROJECT_SLUG": (str, "hope", "hope", False, "Bitcaster project slug"),
    "BITCASTER_APPLICATION_SLUG": (str, "", "country-workspace", False, "Bitcaster application slug"),
}

env = SmartEnv(**CONFIG)
