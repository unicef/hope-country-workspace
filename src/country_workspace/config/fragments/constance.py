from ..settings import NEW_USER_DEFAULT_GROUP

CONSTANCE_BACKEND = "constance.backends.database.DatabaseBackend"


# CONSTANCE_CONFIG_FIELDSETS = {
#     "User settings": {
#         "fields": ("NEW_USER_IS_STAFF", "NEW_USER_DEFAULT_GROUP"),
#         "collapse": False,
#     }
# }

CONSTANCE_ADDITIONAL_FIELDS = {
    "email": [
        "django.forms.EmailField",
        {},
    ],
    "group_select": [
        "country_workspace.utils.constance.GroupSelect",
        {"initial": NEW_USER_DEFAULT_GROUP},
    ],
}

CONSTANCE_CONFIG = {
    "NEW_USER_IS_STAFF": (False, "Set NEW_USER_DEFAULT_GROUP new user as staff", bool),
    "NEW_USER_DEFAULT_GROUP": (
        NEW_USER_DEFAULT_GROUP,
        "Group to assign to any new user",
        "group_select",
    ),
}
