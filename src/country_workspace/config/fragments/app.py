from .. import env

ANALYST_GROUP_NAME = "Analyst"
NEW_USER_DEFAULT_GROUP = "Default"

TENANT_TENANT_MODEL = "country_workspace.Office"
TENANT_HQ = "= HQ ="

AURORA_API_TOKEN = env("AURORA_API_TOKEN")
AURORA_API_URL = env("AURORA_API_URL")

HOPE_API_TOKEN = env("HOPE_API_TOKEN")
HOPE_API_URL = env("HOPE_API_URL")

HH_LOOKUPS = [
    "ResidenceStatus",
]
IND_LOOKUPS = ["Relationship", "Role", "MaritalStatus", "ObservedDisability"]
