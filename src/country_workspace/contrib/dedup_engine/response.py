from enum import StrEnum, auto
from typing import TypedDict


class Status(StrEnum):
    STARTED = auto()
    SUCCESS = auto()
    PENDING = auto()
    FAILURE = auto()
    REVOKED = auto()
    UNKNOWN = auto()


class DeduplicationSet(TypedDict):
    status: str
    duplicates_found: int
