from .app import AURORA_API_TOKEN, AURORA_API_URL, HOPE_API_TOKEN, HOPE_API_URL, NEW_USER_DEFAULT_GROUP
from .dedup import DEDUP_API_URL, DEDUP_API_TOKEN
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
    "write_only_textarea": [
        "django.forms.fields.CharField",
        {
            "required": False,
            "widget": "country_workspace.utils.constance.WriteOnlyTextarea",
        },
    ],
    "write_only_text_input": [
        "django.forms.fields.CharField",
        {
            "required": False,
            "widget": "country_workspace.utils.constance.WriteOnlyTextInput",
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
    "AURORA_API_TOKEN": (AURORA_API_TOKEN, "Aurora API Access Token", "write_only_text_input"),
    "AURORA_API_URL": (AURORA_API_URL, "Aurora API Server address", str),
    "HOPE_API_TOKEN": (HOPE_API_TOKEN, "HOPE API Access Token", "write_only_text_input"),
    "HOPE_API_URL": (HOPE_API_URL, "HOPE API Server address", str),
    "KOBO_API_TOKEN": (KOBO_API_TOKEN, "Kobo API Access Token", "write_only_text_input"),
    "KOBO_MASTER_API_TOKEN": (KOBO_MASTER_API_TOKEN, "Kobo API Master Access Token", "write_only_text_input"),
    "KOBO_PROJECT_VIEW_ID": (KOBO_PROJECT_VIEW_ID, "Kobo Project View ID", str),
    "KOBO_KF_URL": (KOBO_KF_URL, "Kobo Server address", str),
    "KOBO_CACHE_TTL": (86400, "Kobo data cache TTL", int),
    "KOBO_IMPORT_TIMEBOX_MINUTES": (30, "Max minutes before Kobo import reschedules itself", int),
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
    "MAILJET_SECRET_KEY": (MAILJET_SECRET_KEY, "Mailjet secret key", "write_only_text_input"),
    "DEDUP_API_URL": (DEDUP_API_URL, "Dedup Engine server address", str),
    "DEDUP_API_TOKEN": (DEDUP_API_TOKEN, "Dedup Engine API access token", "write_only_text_input"),
    "CHUNK_SIZE_FOR_VALIDATION_TASK": (500, "Number of records to process per chunk in validation tasks", int),
    "PICTURE_IMPORT_MAX_ZIP_UPLOAD_MB": (
        20,
        "Maximum uploaded ZIP size in MB for batch picture import",
        int,
    ),
    "PICTURE_IMPORT_MAX_ZIP_FILE_COUNT": (
        2000,
        "Maximum number of files allowed in a picture import ZIP",
        int,
    ),
    "RDP_CLEANUP_DAYS": (
        30,
        "Number of days to keep Household and Individual data after a successful RDP push. 0 means disabled.",
        int,
    ),
    "RDP_CLEANUP_BATCH_SIZE": (
        5000,
        "Number of records to delete per batch in RDP cleanup task",
        int,
    ),
    "KOBO_FIELDS_TO_IGNORE": (
        "audit, collect_individual_data, deviceid, start, end, hh_geopoint, instanceid, number_alternate, "
        "number_primary, number_repeat, org_name_enumerator, rootuuid, uuid",
        "Comma separated Kobo system specific fields to ignore during data import",
        str,
    ),
    "KOBO_HH_FIELDS_TO_IGNORE": (
        "audit, collect_individual_data, deviceid, end, hh_geopoint, instanceid, number_alternate, "
        "number_primary, number_repeat, org_name_enumerator, rootuuid, uuid",
        "Comma separated default Kobo household fields to ignore during data import",
        str,
    ),
    "KOBO_IND_FIELDS_TO_IGNORE": (
        "",
        "Comma separated default Kobo individual fields to ignore during data import",
        str,
    ),
    "AURORA_HH_FIELDS_TO_IGNORE": (
        "",
        "Comma separated default Aurora household fields to ignore during data import",
        str,
    ),
    "AURORA_IND_FIELDS_TO_IGNORE": (
        "",
        "Comma separated default Aurora individual fields to ignore during data import",
        str,
    ),
    "XLS_HH_FIELDS_TO_IGNORE": (
        "",
        "Comma separated default XLS household fields to ignore during data import",
        str,
    ),
    "XLS_IND_FIELDS_TO_IGNORE": (
        "",
        "Comma separated default XLS individual fields to ignore during data import",
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
        "KOBO_HH_FIELDS_TO_IGNORE",
        "KOBO_IND_FIELDS_TO_IGNORE",
        "KOBO_IMPORT_TIMEBOX_MINUTES",
    ),
    "Remote System Settings - Aurora": (
        "AURORA_API_TOKEN",
        "AURORA_API_URL",
        "AURORA_HH_FIELDS_TO_IGNORE",
        "AURORA_IND_FIELDS_TO_IGNORE",
    ),
    "Remote System Settings - HOPE": (
        "HOPE_API_TOKEN",
        "HOPE_API_URL",
    ),
    "Remote System Settings - Mailjet": (
        "MAILJET_API_KEY",
        "MAILJET_SECRET_KEY",
    ),
    "Data Import Settings - XLS": (
        "XLS_HH_FIELDS_TO_IGNORE",
        "XLS_IND_FIELDS_TO_IGNORE",
    ),
    "Remote System Settings - Dedup Engine": (
        "DEDUP_API_URL",
        "DEDUP_API_TOKEN",
    ),
    "System Settings": (
        "CACHE_TIMEOUT",
        "CACHE_BY_VERSION",
        "CHUNK_SIZE_FOR_VALIDATION_TASK",
        "PICTURE_IMPORT_MAX_ZIP_UPLOAD_MB",
        "PICTURE_IMPORT_MAX_ZIP_FILE_COUNT",
        "RDP_CLEANUP_DAYS",
        "RDP_CLEANUP_BATCH_SIZE",
        "NEW_USER_IS_STAFF",
        "NEW_USER_DEFAULT_GROUP",
        "CONCURRENCY_GUARD",
    ),
}

CONSTANCE_DEFAULTS_MASK = "***"
CONSTANCE_MASKED_DEFAULTS = (
    "AURORA_API_TOKEN",
    "HOPE_API_TOKEN",
    "KOBO_API_TOKEN",
    "KOBO_MASTER_API_TOKEN",
    "MAILJET_SECRET_KEY",
    "DEDUP_API_TOKEN",
)
