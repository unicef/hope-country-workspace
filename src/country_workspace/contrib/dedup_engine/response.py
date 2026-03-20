from enum import StrEnum, auto
from typing import Any, TypedDict


class Status(StrEnum):
    STARTED = auto()
    SUCCESS = auto()
    PENDING = auto()
    FAILURE = auto()
    REVOKED = auto()
    UNKNOWN = auto()
    NOT_SCHEDULED = auto()
    DS_NOT_EXPOSED = auto()
    STATUS_UNAVAILABLE = auto()


class DeduplicationSet(TypedDict):
    id: str
    status: str
    duplicates_found: int


type DeduplicationSetGroupConfig = dict[str, Any]
