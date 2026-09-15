from typing import NotRequired, TypedDict
from .schemas import GroupSettings


class CreatedDeduplicationSet(TypedDict):
    id: NotRequired[str]
    name: NotRequired[str | None]
    notification_url: NotRequired[str | None]
    notify: NotRequired[bool]
    reference_pk: str
    state: str


class DeduplicationSet(TypedDict):
    id: NotRequired[str]
    created_at: str
    findings_count: int
    name: str | None
    reference_pk: str
    state: str
    updated_at: str


class CreatedEncoding(TypedDict):
    reference_pk: str
    filename: str


class FindingEntry(TypedDict):
    reference_pk: int


class Finding(TypedDict):
    first: FindingEntry
    second: FindingEntry
    score: NotRequired[float]
    status_code: NotRequired[int]
    updated_at: str


class PaginatedFindings(TypedDict):
    count: int
    next: NotRequired[str | None]
    results: list[Finding]


class DeduplicationSetGroupConfig(GroupSettings): ...
