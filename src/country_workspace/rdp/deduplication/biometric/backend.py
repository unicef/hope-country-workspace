from country_workspace.contrib.dedup_engine import (
    NON_BLOCKING_DEDUPLICATION_SET_STATES,
    REJECTABLE_DEDUPLICATION_SET_STATES,
    DeduplicationSetState,
)
from country_workspace.models import RdpOperation

from ..backend import DeduplicationBackend
from .remote import approve_operation_set, reject_operation_set, retrieve_operation_state
from .workflow import sync_biometric_result


BIOMETRIC_BACKEND = DeduplicationBackend(
    operation_type=RdpOperation.Type.BIOMETRIC_DEDUPLICATION,
    kind="biometric",
    remote_label="deduplication set",
    sync=sync_biometric_result,
    retrieve_state=retrieve_operation_state,
    approve_remote=approve_operation_set,
    reject_remote=reject_operation_set,
    rejectable_states=frozenset(REJECTABLE_DEDUPLICATION_SET_STATES),
    non_blocking_states=frozenset(NON_BLOCKING_DEDUPLICATION_SET_STATES),
    clean_state=DeduplicationSetState.DEDUPLICATED,
    reject_ignored_states=frozenset({DeduplicationSetState.REJECTED}),
)
