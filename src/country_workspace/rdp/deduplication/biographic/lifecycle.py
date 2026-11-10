from country_workspace.contrib.dedup_engine import (
    NON_BLOCKING_DATASET_STATES,
    REJECTABLE_DATASET_STATES,
    DatasetState,
)
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import RdpOperation
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.policy import ActionCheck

from ..backend import RejectionDecision
from .actions import reject_biographic_dataset
from .remote import retrieve_operation_state


def check_biographic_cancellation(operation: RdpOperation) -> RejectionDecision:
    """Check whether the biographic DedupEngine dataset must be rejected on cancellation."""
    state = retrieve_operation_state(operation)

    if state in REJECTABLE_DATASET_STATES:
        return RejectionDecision(ActionCheck(True), required=True)
    if state is None or state in NON_BLOCKING_DATASET_STATES:
        return RejectionDecision(ActionCheck(True))

    return RejectionDecision(
        ActionCheck(False, f"DedupEngine: can not cancel with biographic dataset in state={state!r}.")
    )


def check_biographic_clean(operation: RdpOperation) -> ActionCheck:
    """Check that the biographic DedupEngine dataset can back a clean replacement RDP."""
    if operation.status != RdpOperation.Status.SUCCESS:
        return ActionCheck(False, "RDP: successful biographic deduplication is required.")

    if (state := retrieve_operation_state(operation)) != DatasetState.DEDUPLICATED:
        return ActionCheck(False, f"DedupEngine: can not create clean RDP with biographic dataset in state={state!r}.")

    return ActionCheck(True)


def reject_cancelled_biographic_dataset(operation: RdpOperation) -> None:
    """Reject the biographic DedupEngine dataset of a cancelled RDP unless it no longer holds the program's slot."""
    try:
        state = retrieve_operation_state(operation)
        if state in REJECTABLE_DATASET_STATES:
            reject_biographic_dataset(operation)
        elif state is not None and state not in NON_BLOCKING_DATASET_STATES:
            raise RdpWorkflowError({"errors": [f"DedupEngine: can not reject biographic dataset in state={state!r}."]})
    except (RemoteError, RemoteUnavailableError) as exc:
        raise RdpWorkflowError({"errors": [str(exc)]}) from exc
