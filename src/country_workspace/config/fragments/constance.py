from ..settings import NEW_USER_DEFAULT_GROUP

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
    "HOPE_API_URL": ("https://hope.unicef.org/api/rest/", "HOPE API Server address", str),
    "HOPE_API_TOKEN": ("", "HOPE API Access Token", "write_only_input"),
    "AURORA_API_URL": ("https://register.unicef.org/api/", "Aurora API Server address", str),
    "AURORA_API_TOKEN": ("", "Aurora API Access Token", "write_only_input"),
    "KOBO_API_URL": ("", "Kobo API Server address", str),
    "KOBO_API_TOKEN": ("", "Kobo API Access Token", "write_only_input"),
}

CONSTANCE_CONFIG_FIELDSETS = {
    "New User Options": ("NEW_USER_IS_STAFF", "NEW_USER_DEFAULT_GROUP"),
    "Remote System Tokens": (
        "HOPE_API_URL",
        "HOPE_API_TOKEN",
        "AURORA_API_URL",
        "AURORA_API_TOKEN",
        "KOBO_API_URL",
        "KOBO_API_TOKEN",
    ),
}
