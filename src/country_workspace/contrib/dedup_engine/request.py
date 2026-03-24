from typing import Any, Literal, TypedDict


class DeduplicationSet(TypedDict):
    reference_pk: str


class Image(TypedDict):
    reference_pk: str
    filename: str


class Approve(TypedDict):
    action: Literal["approve"]


class Reject(TypedDict):
    action: Literal["reject"]


type DeduplicationSetGroupConfig = dict[str, Any]
