from enum import StrEnum


class PushReadyCallbackCode(StrEnum):
    QUEUED = "queued"
    IGNORED = "ignored"
