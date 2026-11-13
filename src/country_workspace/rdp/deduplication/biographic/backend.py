from country_workspace.contrib.dedup_engine import (
    NON_BLOCKING_DATASET_STATES,
    REJECTABLE_DATASET_STATES,
    DatasetState,
)
from country_workspace.models import RdpOperation

from ..backend import DeduplicationBackend
from .remote import approve_operation_dataset, reject_operation_dataset, retrieve_operation_state
from .workflow import sync_biographic_result


BIOGRAPHIC_BACKEND = DeduplicationBackend(
    operation_type=RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION,
    kind="biographic",
    remote_label="biographic dataset",
    sync=sync_biographic_result,
    retrieve_state=retrieve_operation_state,
    approve_remote=approve_operation_dataset,
    reject_remote=reject_operation_dataset,
    rejectable_states=frozenset(REJECTABLE_DATASET_STATES),
    non_blocking_states=frozenset(NON_BLOCKING_DATASET_STATES),
    clean_state=DatasetState.DEDUPLICATED,
    # A dataset that holds no slot (pending, failed, canceled, approved, rejected) has nothing left to reject.
    reject_ignored_states=frozenset(NON_BLOCKING_DATASET_STATES),
)
