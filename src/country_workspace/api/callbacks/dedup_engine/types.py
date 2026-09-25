from enum import StrEnum, auto


class DedupCallbackCode(StrEnum):
    UPDATED = auto()
    UNCHANGED = auto()
