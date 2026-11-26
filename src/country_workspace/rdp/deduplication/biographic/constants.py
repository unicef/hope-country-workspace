from typing import Final

from .types import BiographicFindingType


# Individuals sent to DedupEngine per request (it accepts up to 10,000).
BIOGRAPHIC_RECORDS_BATCH_SIZE: Final[int] = 1000

# Every biographic finding is a duplicate: DedupEngine reports no "possible duplicate" tier.
BIOGRAPHIC_AFFECTING_FINDING_TYPES: Final[frozenset[str]] = frozenset({BiographicFindingType.DUPLICATE.value})

# Individual flex fields scored by DedupEngine, named as in HOPE.
BIOGRAPHIC_FULL_NAME_FIELD: Final[str] = "full_name"
BIOGRAPHIC_BIRTH_DATE_FIELD: Final[str] = "birth_date"
BIOGRAPHIC_TEXT_FIELDS: Final[tuple[str, ...]] = (
    "given_name",
    "family_name",
    "middle_name",
    "phone_no",
    "phone_no_alternative",
    "sex",
    "relationship",
)
