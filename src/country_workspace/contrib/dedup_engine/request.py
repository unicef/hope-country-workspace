from typing import NotRequired, TypedDict
from .schemas import GroupSettings


class CreateDeduplicationSet(TypedDict):
    id: NotRequired[str]
    name: NotRequired[str | None]
    notification_url: NotRequired[str | None]
    notify: NotRequired[bool]
    reference_pk: str


class DeduplicationSetGroupConfig(GroupSettings): ...


class CreateEncoding(TypedDict):
    filename: str
    reference_pk: str
