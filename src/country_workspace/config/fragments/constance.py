from .app import AURORA_API_TOKEN, AURORA_API_URL, HOPE_API_TOKEN, HOPE_API_URL, NEW_USER_DEFAULT_GROUP
from .kobo import KOBO_TOKEN, KOBO_BASE_URL

CONSTANCE_BACKEND = "constance.backends.database.DatabaseBackend"


CONSTANCE_ADDITIONAL_FIELDS = {
    "email": [
        "django.forms.EmailField",
        {},
    ],
    "group_select": [
        "country_workspace.utils.constance.GroupChoiceField",
        {"initial": NEW_USER_DEFAULT_GROUP},
    ],
    "read_only_text": [
        "django.forms.fields.CharField",
        {
            "required": False,
            "widget": "country_workspace.utils.constance.ObfuscatedInput",
        },
    ],
    "write_only_text": [
        "django.forms.fields.CharField",
        {
            "required": False,
            "widget": "country_workspace.utils.constance.WriteOnlyTextarea",
        },
    ],
    "write_only_input": [
        "django.forms.fields.CharField",
        {
            "required": False,
            "widget": "country_workspace.utils.constance.WriteOnlyInput",
        },
    ],
}

CONSTANCE_CONFIG = {
    "NEW_USER_IS_STAFF": (False, "Set NEW_USER_DEFAULT_GROUP new user as staff", bool),
    "NEW_USER_DEFAULT_GROUP": (
        NEW_USER_DEFAULT_GROUP,
        "Group to assign to any new user",
        "group_select",
    ),
    "AURORA_API_TOKEN": (AURORA_API_TOKEN, "Aurora API Access Token", "write_only_input"),
    "AURORA_API_URL": (AURORA_API_URL, "Aurora API Server address", str),
    "HOPE_API_TOKEN": (HOPE_API_TOKEN, "HOPE API Access Token", "write_only_input"),
    "HOPE_API_URL": (HOPE_API_URL, "HOPE API Server address", str),
    "KOBO_TOKEN": (KOBO_TOKEN, "Kobo API Access Token", "write_only_input"),
    "KOBO_BASE_URL": (KOBO_BASE_URL, "Kobo Server address", str),
    "CACHE_TIMEOUT": (86400, "Cache Redis TTL", int),
    "CACHE_BY_VERSION": (False, "Invalidate Cache on CW version change", bool),
    "CONCURRENCY_GUARD": (
        True,
        "Prevent updates if data has changed after export. When enabled, the system will reject updates to records"
        " that were modified after they were exported. This helps maintain data consistency and prevents accidental"
        " overwrites of newer information.",
        bool,
    ),
}

CONSTANCE_CONFIG_FIELDSETS = {
    "New User Options": ("NEW_USER_IS_STAFF", "NEW_USER_DEFAULT_GROUP"),
    "Cache": ("CACHE_TIMEOUT", "CACHE_BY_VERSION"),
    "Remote System Tokens": (
        "AURORA_API_TOKEN",
        "AURORA_API_URL",
        "HOPE_API_TOKEN",
        "HOPE_API_URL",
        "KOBO_TOKEN",
        "KOBO_BASE_URL",
    ),
    "Data consistency": ("CONCURRENCY_GUARD",),
}

# Mapping of config keys to masked default display values in the Constance admin UI.
CONSTANCE_MASKED_DEFAULTS = {
    "AURORA_API_TOKEN": "***",
    "HOPE_API_TOKEN": "***",
    "KOBO_API_TOKEN": "***",
}
