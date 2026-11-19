from enum import StrEnum


class DeduplicationLogAction(StrEnum):
    APPROVE_SET = "APPROVE_DEDUPLICATION_SET"
    REJECT_SET = "REJECT_DEDUPLICATION_SET"
