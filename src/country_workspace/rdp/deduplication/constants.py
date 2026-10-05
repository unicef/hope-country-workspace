from typing import Final

from country_workspace.contrib.dedup_engine import FindingStatusCode


DEDUP_CALLBACK_MAX_AGE: Final[int] = 60 * 60 * 96  # 96 hours
DEDUP_CALLBACK_SALT: Final[str] = "country_workspace.deduplication.callback"

IMAGES_TO_DEDUPLICATE_BULK_BATCH_SIZE: Final[int] = 10

BIOMETRIC_IMAGE_ISSUE_FINDING_TYPES: Final[frozenset[str]] = frozenset(
    {
        FindingStatusCode.FILE_NOT_FOUND.name,
        FindingStatusCode.NO_FACE_DETECTED.name,
        FindingStatusCode.FACE_NOT_ACCEPTED.name,
        FindingStatusCode.BAD_IMAGE_QUALITY.name,
        FindingStatusCode.MULTIPLE_FACES_DETECTED.name,
    }
)

BIOMETRIC_AFFECTING_FINDING_TYPES: Final[frozenset[str]] = BIOMETRIC_IMAGE_ISSUE_FINDING_TYPES | {
    FindingStatusCode.DUPLICATE.name
}
