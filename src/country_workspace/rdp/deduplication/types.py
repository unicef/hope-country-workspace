from enum import StrEnum, auto


class ThresholdType(StrEnum):
    COUNT = auto()
    RATE = auto()


class DeduplicationLogAction(StrEnum):
    APPROVE_SET = "APPROVE_DEDUPLICATION_SET"
    REJECT_SET = "REJECT_DEDUPLICATION_SET"
