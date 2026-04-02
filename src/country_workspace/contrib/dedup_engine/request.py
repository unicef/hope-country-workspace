from typing import NotRequired, TypedDict
from .schemas import GroupSettings


class CreateDeduplicationSet(TypedDict):
    id: NotRequired[str]
    name: NotRequired[str | None]
    notification_url: NotRequired[str | None]
    notify: NotRequired[bool]
    reference_pk: str


class DeduplicationSetGroupConfig(GroupSettings):
    pass


class CreateEncoding(TypedDict):
    deduplication_set: NotRequired[str]
    filename: str
    reference_pk: str
