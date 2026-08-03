from typing import Final

PUSH_BATCH_SIZE: Final[int] = 10
IMAGES_TO_DEDUPLICATE_BULK_BATCH_SIZE: Final[int] = 10

# NEVER CHANGE THIS VALUES
HOUSEHOLD_CHECKER_NAME: Final[str] = "HOPE Household core"
INDIVIDUAL_CHECKER_NAME: Final[str] = "HOPE Individual core"
PEOPLE_CHECKER_NAME: Final[str] = "HOPE People core"

HOUSEHOLD_FIELDSET_NAME: Final[str] = "HOPE Household core"
INDIVIDUAL_BASE_FIELDSET_NAME = "HOPE Individual core base"
INDIVIDUAL_FIELDSET_NAME: Final[str] = "HOPE Individual core"
PEOPLE_FIELDSET_NAME: Final[str] = "HOPE People core"
ADMINAREAS_FIELDSET_NAME: Final[str] = "HOPE Admin Areas"
ACCOUNT_FIELDSET_NAME: Final[str] = "HOPE Account"
DOCUMENT_FIELDSET_NAME: Final[str] = "HOPE Document"

DOCUMENT_TYPES = ("national_id", "national_passport")
MAX_DOCUMENT_COLUMNS = 3
ACCOUNT_TYPES = ("mobile", "bank")

# HOPE push-ready callback
PUSH_READY_CALLBACK_SALT: Final[str] = "push_ready_callback"
