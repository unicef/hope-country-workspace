from typing import Literal, NotRequired, TypedDict


class Dataset(TypedDict):
    dataset_id: str
    status: str
    error: str | None
    records_count: int
    batch_duplicates: int
    population_duplicates: int
    notification_url: str | None
    notify: bool
    created_at: str
    updated_at: str


class Finding(TypedDict):
    reference_pk: str
    matched_reference_pk: str
    scope: Literal["batch", "population"]
    score: float
    proximity_to_score: float
    matched_full_name: str
    matched_birth_date: str | None


class PaginatedFindings(TypedDict):
    count: int
    next: NotRequired[str | None]
    results: list[Finding]


class RecordsBatchResult(TypedDict):
    received: int
    records_count: int
