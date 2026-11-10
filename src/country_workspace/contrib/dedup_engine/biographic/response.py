from typing import Literal, NotRequired, TypedDict


class Dataset(TypedDict):
    dataset_id: int
    status: str
    error: str | None
    records_count: int
    batch_duplicates: int
    population_duplicates: int
    notification_url: NotRequired[str | None]
    notify: NotRequired[bool]
    created_at: NotRequired[str]
    updated_at: NotRequired[str]


class Finding(TypedDict):
    reference_pk: str
    matched_reference_pk: str
    scope: Literal["batch", "population"]
    score: float
    proximity_to_score: float
    matched_full_name: str | None
    matched_birth_date: str | None


class PaginatedFindings(TypedDict):
    count: int
    next: NotRequired[str | None]
    results: list[Finding]


class RecordsBatchResult(TypedDict):
    received: int
    records_count: int
