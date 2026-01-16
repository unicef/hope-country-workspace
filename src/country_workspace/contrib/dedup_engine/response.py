from enum import StrEnum, auto
from typing import TypedDict


class Status(StrEnum):
    STARTED = auto()
    SUCCESS = auto()
    UNKNOWN = auto()


class DeduplicationSet(TypedDict):
    status: str
