from enum import IntEnum
from typing import NotRequired, TypedDict


class GroupSettings(TypedDict):
    face_detection_confidence_threshold: NotRequired[float]
    duplicate_confidence_threshold: NotRequired[float]
    sharpness_threshold: NotRequired[float]
    dynamic_range_threshold: NotRequired[float]
    no_head_cover_threshold: NotRequired[float]
    eyes_open_threshold: NotRequired[float]
    inter_eye_distance_threshold: NotRequired[float]
    unified_quality_score_threshold: NotRequired[float]


class FindingStatusCode(IntEnum):
    DUPLICATE = 200
    FILE_NOT_FOUND = 404
    NO_FACE_DETECTED = 412
    FACE_NOT_ACCEPTED = 416
    BAD_IMAGE_QUALITY = 418
    MULTIPLE_FACES_DETECTED = 429
    GENERIC_ERROR = 500


SYSTEM_ERROR_STATUS_CODES = frozenset(
    {
        FindingStatusCode.FILE_NOT_FOUND,
        FindingStatusCode.GENERIC_ERROR,
    }
)
