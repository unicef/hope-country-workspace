from enum import StrEnum, auto
from typing import TypedDict


class Status(StrEnum):
    STARTED = auto()
    SUCCESS = auto()
    PENDING = auto()
    FAILURE = auto()
    REVOKED = auto()
    UNKNOWN = auto()
    NOT_SCHEDULED = auto()


class DeduplicationSet(TypedDict):
    id: str
    status: str
    duplicates_found: int
