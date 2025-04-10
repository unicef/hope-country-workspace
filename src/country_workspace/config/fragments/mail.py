from .. import env

DEFAULT_FROM_EMAIL = "hope@unicef.org"
SERVER_EMAIL = "root@localhost"
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

ANYMAIL = {
    "MAILJET_API_URL": env("MAILJET_API_URL", default="https://api.mailjet.com/v3.1/"),
    "MAILJET_API_KEY": (MAILJET_API_KEY := env("MAILJET_API_KEY")),
    "MAILJET_SECRET_KEY": (MAILJET_SECRET_KEY := env("MAILJET_SECRET_KEY")),
    "IGNORE_RECIPIENT_STATUS": env("IGNORE_RECIPIENT_STATUS", default=True),
    "IGNORE_UNSUPPORTED_FEATURES": env("IGNORE_UNSUPPORTED_FEATURES", default=True),
    "REQUESTS_TIMEOUT": env("REQUESTS_TIMEOUT", default=30),
    "DEBUG_API_REQUESTS": env("DEBUG_API_REQUESTS", default=False),
}
