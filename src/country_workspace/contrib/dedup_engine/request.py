from typing import TypedDict, Any, Literal


class DeduplicationSet(TypedDict):
    reference_pk: str
    settings: dict[str, Any]


class Image(TypedDict):
    reference_pk: str
    filename: str


class ReferencePks(TypedDict):
    reference_pks: list[str]


class Approve(ReferencePks):
    action: Literal["approve"]


class Reject(ReferencePks):
    action: Literal["reject"]
