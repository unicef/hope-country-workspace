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


class DeduplicationSetGroupConfig(GroupSettings):
    pass


class CreatedEncoding(TypedDict):
    reference_pk: str
    filename: str
