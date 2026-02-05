from enum import StrEnum, auto
from typing import TypedDict


class Status(StrEnum):
    STARTED = auto()
    SUCCESS = auto()
    PENDING = auto()
    FAILURE = auto()
    REVOKED = auto()
    NOT_SCHEDULED = auto()
    UNKNOWN = auto()


class State(StrEnum):
    READY = auto()
    MODIFIED = auto()
    PROCESSING = auto()
    FAILED = auto()
    INACTIVE = auto()
    UNKNOWN = auto()


class DeduplicationSet(TypedDict):
    id: str
    status: str
    duplicates_found: int
