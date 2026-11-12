from typing import Final

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
ACCOUNT_ATTACHMENTS_FIELD: Final[str] = "attachments"

# Limits of HOPE Core's AccountAttachment: HOPE rejects anything beyond them.
ACCOUNT_ATTACHMENT_LIMIT: Final[int] = 10
ACCOUNT_ATTACHMENT_SIZE_LIMIT: Final[int] = 10 * 1024 * 1024
ACCOUNT_ATTACHMENT_EXTENSIONS: Final[tuple[str, ...]] = ("pdf", "xlsx", "jpg", "jpeg", "png")
ACCOUNT_ATTACHMENT_TITLE_MAX_LENGTH: Final[int] = 255
