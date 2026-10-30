from enum import StrEnum
from typing import Final, NotRequired, TypedDict


class BiographicSetState(StrEnum):
    """Lifecycle states of a biographic set, as returned by DedupEngine in `status`."""

    PENDING = "pending"
    INDEXING = "indexing"
    INDEXED = "indexed"
    DEDUPLICATING = "deduplicating"
    DEDUPLICATED = "deduplicated"
    FAILED = "failed"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELED = "canceled"


class FindingScope(StrEnum):
    """Where a finding's matched person comes from."""

    BATCH = "batch"
    POPULATION = "population"


# The worker is busy with the set: wait for a notification.
RUNNING_BIOGRAPHIC_SET_STATES: Final[tuple[BiographicSetState, ...]] = (
    BiographicSetState.INDEXING,
    BiographicSetState.INDEXED,
    BiographicSetState.DEDUPLICATING,
)

# A run can be (re)started for the set.
PROCESSABLE_BIOGRAPHIC_SET_STATES: Final[tuple[BiographicSetState, ...]] = (
    BiographicSetState.PENDING,
    BiographicSetState.FAILED,
)

# Scored and waiting for a decision: the client may approve or reject.
REJECTABLE_BIOGRAPHIC_SET_STATES: Final[tuple[BiographicSetState, ...]] = (BiographicSetState.DEDUPLICATED,)

# The set no longer holds the program's single processing slot and takes no more decisions.
NON_BLOCKING_BIOGRAPHIC_SET_STATES: Final[tuple[BiographicSetState, ...]] = (
    BiographicSetState.PENDING,
    BiographicSetState.FAILED,
    BiographicSetState.APPROVED,
    BiographicSetState.REJECTED,
    BiographicSetState.CANCELED,
)


class BiographicPayload(TypedDict):
    """Scoreable fields of one person. Only `full_name` is required by DedupEngine."""

    full_name: str
    given_name: NotRequired[str | None]
    family_name: NotRequired[str | None]
    middle_name: NotRequired[str | None]
    birth_date: NotRequired[str | None]
    phone_no: NotRequired[str | None]
    phone_no_alternative: NotRequired[str | None]
    sex: NotRequired[str | None]
    relationship: NotRequired[str | None]


class BiographicRecord(TypedDict):
    reference_pk: str
    payload: BiographicPayload


class CreateBiographicSet(TypedDict, total=False):
    notification_url: str
    notify: bool


class BiographicSet(TypedDict):
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


class RecordsBatchResult(TypedDict):
    received: int
    records_count: int


class BiographicFinding(TypedDict):
    reference_pk: str
    matched_reference_pk: str
    scope: str
    score: float
    proximity_to_score: float
    matched_full_name: str | None
    matched_birth_date: str | None


class PaginatedBiographicFindings(TypedDict):
    count: int
    next: NotRequired[str | None]
    previous: NotRequired[str | None]
    results: list[BiographicFinding]
