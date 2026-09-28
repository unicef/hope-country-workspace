from enum import StrEnum, auto


class PushReadyCallbackCode(StrEnum):
    SCHEDULED = auto()
    IGNORED = auto()
