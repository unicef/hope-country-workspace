from typing import TypedDict, Any


class DeduplicationSet(TypedDict):
    reference_pk: str
    settings: dict[str, Any]


class Image(TypedDict):
    reference_pk: str
    filename: str
