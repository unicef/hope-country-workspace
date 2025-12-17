from .app import AURORA_API_TOKEN, AURORA_API_URL, HOPE_API_TOKEN, HOPE_API_URL, NEW_USER_DEFAULT_GROUP
from .kobo import KOBO_API_TOKEN, KOBO_KF_URL, KOBO_MASTER_API_TOKEN, KOBO_PROJECT_VIEW_ID
from .mail import MAILJET_API_KEY, MAILJET_SECRET_KEY

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
    "KOBO_API_TOKEN": (KOBO_API_TOKEN, "Kobo API Access Token", "write_only_input"),
    "KOBO_MASTER_API_TOKEN": (KOBO_MASTER_API_TOKEN, "Kobo API Master Access Token", "write_only_input"),
    "KOBO_PROJECT_VIEW_ID": (KOBO_PROJECT_VIEW_ID, "Kobo Project View ID", str),
    "KOBO_KF_URL": (KOBO_KF_URL, "Kobo Server address", str),
    "KOBO_CACHE_TTL": (86400, "Kobo data cache TTL", int),
    "CACHE_TIMEOUT": (86400, "Cache Redis TTL", int),
    "CACHE_BY_VERSION": (False, "Invalidate Cache on CW version change", bool),
    "CONCURRENCY_GUARD": (
        True,
        "Prevent updates if data has changed after export. When enabled, the system will reject updates to records"
        " that were modified after they were exported. This helps maintain data consistency and prevents accidental"
        " overwrites of newer information.",
        bool,
    ),
    "MAILJET_API_KEY": (MAILJET_API_KEY, "Mailjet API key", str),
    "MAILJET_SECRET_KEY": (MAILJET_SECRET_KEY, "Mailjet secret key", "write_only_input"),
    "CHUNK_SIZE_FOR_VALIDATION_TASK": (500, "Number of records to process per chunk in validation tasks", int),
    "KOBO_FIELDS_TO_IGNORE": (
        "audit, collect_individual_data, deviceid, start, end, hh_geopoint, instanceid, number_alternate, "
        "number_primary, number_repeat, org_name_enumerator, rootuuid, uuid",
        "Comma separated Kobo system specific fields to ignore during data import",
        str,
    ),
}

CONSTANCE_CONFIG_FIELDSETS = {
    "Remote System Settings - Kobo": (
        "KOBO_API_TOKEN",
        "KOBO_MASTER_API_TOKEN",
        "KOBO_PROJECT_VIEW_ID",
        "KOBO_KF_URL",
        "KOBO_CACHE_TTL",
        "KOBO_FIELDS_TO_IGNORE",
    ),
    "Remote System Settings - Aurora": (
        "AURORA_API_TOKEN",
        "AURORA_API_URL",
    ),
    "Remote System Settings - HOPE": (
        "HOPE_API_TOKEN",
        "HOPE_API_URL",
    ),
    "Remote System Settings - Mailjet": (
        "MAILJET_API_KEY",
        "MAILJET_SECRET_KEY",
    ),
    "System Settings": (
        "CACHE_TIMEOUT",
        "CACHE_BY_VERSION",
        "CHUNK_SIZE_FOR_VALIDATION_TASK",
        "NEW_USER_IS_STAFF",
        "NEW_USER_DEFAULT_GROUP",
        "CONCURRENCY_GUARD",
    ),
}

# Mapping of config keys to masked default display values in the Constance admin UI.
CONSTANCE_MASKED_DEFAULTS = {
    "AURORA_API_TOKEN": "***",
    "HOPE_API_TOKEN": "***",
    "KOBO_API_TOKEN": "***",
    "KOBO_API_MASTER_TOKEN": "***",
    "MAILJET_SECRET_KEY": "***",
}
