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
