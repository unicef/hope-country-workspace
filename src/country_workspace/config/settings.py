from pathlib import Path

from . import env

SETTINGS_DIR = Path(__file__).parent
PACKAGE_DIR = SETTINGS_DIR.parent
DEVELOPMENT_DIR = PACKAGE_DIR.parent.parent

DEBUG = env.bool("DEBUG")

DATABASES = {
    "default": env.db("DATABASE_URL"),
}

INSTALLED_APPS = (
    "country_workspace.web",
    "country_workspace.workspaces.theme",
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.humanize",
    "django.contrib.messages",
    "django.contrib.sessions",
    "django.contrib.sites",
    "django.contrib.sitemaps",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "country_workspace.apps.HCWAdminConfig",
    # ddt
    "debug_toolbar",
    "django_sysinfo",
    "flags",
    "reversion",
    "tailwind",
    "django_select2",
    "social_django",
    "admin_extra_buttons",
    "adminactions",
    "adminfilters",
    "adminfilters.depot",
    "constance",
    "jsoneditor",
    "django_celery_beat",
    "django_celery_results",
    "django_celery_boost",
    "hope_flex_fields",
    "hope_smart_import",
    "hope_smart_export",
    "smart_env",
    "country_workspace.security",
    "country_workspace.apps.HCWConfig",
    "country_workspace.workspaces.apps.Config",
    "country_workspace.versioning",
    "country_workspace.cache",
    # these should be optional in the future
    "country_workspace.contrib.hope.apps.Config",
    "country_workspace.contrib.aurora.apps.Config",
    *env("EXTRA_APPS"),
)

MIDDLEWARE = (
    "country_workspace.middleware.state.StateClearMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "country_workspace.middleware.state.StateSetMiddleware",
    "country_workspace.cache.middleware.UpdateCacheMiddleware",
    "django.middleware.common.CommonMiddleware",
    "csp.middleware.CSPMiddleware",
    "debug_toolbar.middleware.DebugToolbarMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "country_workspace.middleware.exception.ExceptionMiddleware",
    "country_workspace.cache.middleware.FetchFromCacheMiddleware",
    *env("EXTRA_MIDDLEWARES"),
)

AUTHENTICATION_BACKENDS = (
    "social_core.backends.azuread_tenant.AzureADTenantOAuth2",
    "django.contrib.auth.backends.ModelBackend",
    "country_workspace.workspaces.backend.TenantBackend",
    *env("EXTRA_AUTHENTICATION_BACKENDS"),
)

# path
MEDIA_ROOT = env("MEDIA_ROOT")
MEDIA_URL = env("MEDIA_URL")
STATIC_ROOT = env("STATIC_ROOT")
STATIC_URL = env("STATIC_URL")
# #
STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
]

STORAGES = {
    "default": env.storage("FILE_STORAGE_DEFAULT"),
    "staticfiles": env.storage("FILE_STORAGE_STATIC"),
    "media": env.storage("FILE_STORAGE_MEDIA"),
}

SECRET_KEY = env("SECRET_KEY")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_URL = "/accounts/logout"
LOGOUT_REDIRECT_URL = "/"

TIME_ZONE = env("TIME_ZONE")

# Language code for this installation. All choices can be found here:
# http://www.i18nguy.com/unicode/language-identifiers.html
LANGUAGE_CODE = "en-us"
ugettext = lambda s: s  # noqa
LANGUAGES = (
    ("es", ugettext("Spanish")),  # type: ignore[no-untyped-call]
    ("fr", ugettext("French")),  # type: ignore[no-untyped-call]
    ("en", ugettext("English")),  # type: ignore[no-untyped-call]
    ("ar", ugettext("Arabic")),  # type: ignore[no-untyped-call]
)

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
SITE_ID = 1
INTERNAL_IPS = ["127.0.0.1", "localhost"]

USE_I18N = True
USE_TZ = True

CACHE_URL = env("CACHE_URL")
SELECT2_CACHE = env("SELECT2_CACHE")
CACHES = {
    "default": {
        "BACKEND": "redis_lock.django_cache.RedisCache",
        "LOCATION": CACHE_URL,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    },
    "select2": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": SELECT2_CACHE or CACHE_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    },
}
SELECT2_CACHE_BACKEND = "select2"

X_FRAME_OPTIONS = "SAMEORIGIN"

ROOT_URLCONF = "country_workspace.config.urls"
WSGI_APPLICATION = "country_workspace.config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [str(PACKAGE_DIR / "templates")],
        "APP_DIRS": False,
        "OPTIONS": {
            "loaders": [
                "django.template.loaders.app_directories.Loader",
                "django.template.loaders.filesystem.Loader",
            ],
            "context_processors": [
                "constance.context_processors.config",
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "social_django.context_processors.backends",
                "social_django.context_processors.login_redirect",
                "country_workspace.web.context_processors.current_state",
            ],
            "libraries": {
                "staticfiles": "django.templatetags.static",
                "i18n": "django.templatetags.i18n",
            },
        },
    },
]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "": {
            "handlers": ["console"],
            "level": env("LOGGING_LEVEL"),
            "propagate": True,
        },
        "celery": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
        "faker": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
        "factory": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}
SILENCED_SYSTEM_CHECKS = ["admin.E108"]

CSRF_COOKIE_SECURE = env("CSRF_COOKIE_SECURE")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

AUTH_USER_MODEL = "country_workspace.User"
SUPERUSERS = env("SUPERUSERS")

DEFAULT_FROM_EMAIL = "hope@unicef.org"
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_PORT = env("EMAIL_PORT", default=25)
EMAIL_USE_TLS = env("EMAIL_USE_TLS", default=False)
EMAIL_USE_SSL = env("EMAIL_USE_SSL", default=False)

from .fragments.app import *  # noqa
from .fragments.celery import *  # noqa
from .fragments.constance import *  # noqa
from .fragments.csp import *  # noqa
from .fragments.debug_toolbar import *  # noqa
from .fragments.flags import *  # noqa
from .fragments.jsoneditor import *  # noqa
from .fragments.rest_framework import *  # noqa
from .fragments.root import *  # noqa
from .fragments.sentry import *  # noqa
from .fragments.kobo import *  # noqa

# from .fragments.smart_admin import *  # noqa
from .fragments.social_auth import *  # noqa
from .fragments.spectacular import *  # noqa
from .fragments.tailwind import *  # noqa
