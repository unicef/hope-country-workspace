from typing import Final

PUSH_BATCH_SIZE: Final[int] = 25

# NEVER CHANGE THIS VALUES
HOUSEHOLD_CHECKER_NAME: Final[str] = "HOPE Household core"
INDIVIDUAL_CHECKER_NAME: Final[str] = "HOPE Individual core"
PEOPLE_CHECKER_NAME: Final[str] = "HOPE People core"

HOUSEHOLD_FIELDSET_NAME: Final[str] = "HOPE Household core"
INDIVIDUAL_FIELDSET_NAME: Final[str] = "HOPE Individual core"
PEOPLE_FIELDSET_NAME: Final[str] = "HOPE People core"
ADMINAREAS_FIELDSET_NAME: Final[str] = "HOPE Admin Areas"
ACCOUNT_FIELDSET_NAME: Final[str] = "HOPE Account"
DOCUMENT_FIELDSET_NAME: Final[str] = "HOPE Document"

# Updated document types to match HOPE Core API
DOCUMENT_TYPES = ("national_id", "national_passport", "birth_certificate", "other")

# Updated account types to match HOPE Core API
ACCOUNT_TYPES = ("mobile", "bank", "cash", "other")

# Field mappings for HOPE Core API transformation
INDIVIDUAL_FIELD_MAPPINGS = {
    "given_name": "first_name",
    "family_name": "last_name",
    "birth_date": "birth_date",
    "marital_status": "marital_status",
    "observed_disability": "observed_disability",
    "relationship": "relationship",
    "gender": "gender",
    "residence_status": "residence_status",
    "consent_sharing": "consent_sharing",
    "phone_no": "phone_no",
    "phone_no_alternative": "phone_no_alternative",
    "country": "country",
    "country_origin": "country_origin",
    "village": "village",
}

# Required fields for individual data
INDIVIDUAL_REQUIRED_FIELDS = {
    "first_name": "",
    "last_name": "",
    "birth_date": None,  # This must be provided
    "marital_status": "",
    "observed_disability": "",
}

HOUSEHOLD_FIELD_MAPPINGS = {
    "household_size": "size",
    "village": "village",
    "consent_sharing": "consent_sharing",
    "country": "country",
    "country_origin": "country_origin",
    "head_of_household_id": "head_of_household",
    "primary_collector_id": "primary_collector",
    "alternate_collector_id": "alternate_collector",
}

# Administrative area field mappings
ADMIN_AREA_MAPPINGS = {
    "admin1": "admin1",
    "admin2": "admin2",
    "admin3": "admin3",
    "admin4": "admin4",
}

# Document type validation mapping
DOCUMENT_TYPE_MAPPING = {
    "national_id": "national_id",
    "national_passport": "national_passport",
    "birth_certificate": "birth_certificate",
    "other": "other",
}

# Account type validation mapping
ACCOUNT_TYPE_MAPPING = {
    "mobile": "mobile",
    "bank": "bank",
    "cash": "cash",
    "other": "other",
}
