from enum import StrEnum, auto


class ThresholdType(StrEnum):
    COUNT = auto()
    PERCENT = auto()


class DeduplicationLogAction(StrEnum):
    APPROVE_SET = "APPROVE_DEDUPLICATION_SET"
