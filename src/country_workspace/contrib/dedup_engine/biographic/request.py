from typing import NotRequired, TypedDict


class Payload(TypedDict):
    full_name: str
    given_name: NotRequired[str | None]
    family_name: NotRequired[str | None]
    middle_name: NotRequired[str | None]
    birth_date: NotRequired[str | None]
    phone_no: NotRequired[str | None]
    phone_no_alternative: NotRequired[str | None]
    sex: NotRequired[str | None]
    relationship: NotRequired[str | None]


class Record(TypedDict):
    reference_pk: str
    payload: Payload


class CreateDataset(TypedDict, total=False):
    notification_url: str
    notify: bool


class RecordsBatch(TypedDict):
    records: list[Record]


class ProcessOverrides(TypedDict, total=False):
    duplicate_score: float
    max_hits: int
