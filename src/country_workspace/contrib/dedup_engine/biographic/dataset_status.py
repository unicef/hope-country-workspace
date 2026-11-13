from enum import StrEnum
from typing import Final
from uuid import UUID

from country_workspace.exceptions import RemoteError

from .factory import make_client
from .response import Dataset


class DatasetState(StrEnum):
    """Lifecycle states of a biographic dataset, as returned by DedupEngine in `status`."""

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
    """Where the matched person of a finding comes from."""

    BATCH = "batch"
    POPULATION = "population"


# The worker is busy with the dataset: wait for the notification.
RUNNING_DATASET_STATES: Final[tuple[DatasetState, ...]] = (
    DatasetState.INDEXING,
    DatasetState.INDEXED,
    DatasetState.DEDUPLICATING,
)

# A run can be (re)started for the dataset.
PROCESSABLE_DATASET_STATES: Final[tuple[DatasetState, ...]] = (
    DatasetState.PENDING,
    DatasetState.FAILED,
)

# Scored and waiting for a decision: the client may approve or reject.
REJECTABLE_DATASET_STATES: Final[tuple[DatasetState, ...]] = (DatasetState.DEDUPLICATED,)

# The dataset no longer holds the program's processing slot and takes no more decisions.
NON_BLOCKING_DATASET_STATES: Final[tuple[DatasetState, ...]] = (
    DatasetState.PENDING,
    DatasetState.FAILED,
    DatasetState.APPROVED,
    DatasetState.REJECTED,
    DatasetState.CANCELED,
)


def parse_dataset_state(payload: Dataset) -> DatasetState:
    """Return the validated state of a dataset response."""
    try:
        return DatasetState(payload["status"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RemoteError(f"DedupEngine: malformed dataset response: {payload!r}") from exc


def retrieve_dataset_state(
    *,
    business_area_slug: str,
    program_code: str,
    dataset_id: UUID | str,
) -> DatasetState | None:
    """Return the current state of a dataset, or None when DedupEngine does not know it."""
    with make_client(
        business_area_slug=business_area_slug,
        program_code=program_code,
        dataset_id=dataset_id,
    ) as client:
        if (payload := client.retrieve_dataset_or_none()) is None:
            return None
    return parse_dataset_state(payload)
