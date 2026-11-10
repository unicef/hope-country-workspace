from country_workspace.contrib.dedup_engine import (
    NON_BLOCKING_DEDUPLICATION_SET_STATES,
    REJECTABLE_DEDUPLICATION_SET_STATES,
    DeduplicationSetState,
    retrieve_deduplication_set_state,
)
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import RdpOperation
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.policy import ActionCheck

from ..backend import RejectionDecision
from .actions import approve_deduplication_set_after_successful_push, reject_deduplication_set


def _remote_state(operation: RdpOperation) -> DeduplicationSetState | None:
    """Return the DedupEngine state of the operation set, or None when it does not exist."""
    return retrieve_deduplication_set_state(
        group_reference_id=operation.rdp.program.unicef_id,
        deduplication_set_id=str(operation.id),
    )


def check_biometric_cancellation(operation: RdpOperation) -> RejectionDecision:
    """Check whether the biometric DedupEngine set must be rejected on cancellation."""
    state = _remote_state(operation)

    if state in REJECTABLE_DEDUPLICATION_SET_STATES:
        return RejectionDecision(ActionCheck(True), required=True)
    if state is None or state in NON_BLOCKING_DEDUPLICATION_SET_STATES:
        return RejectionDecision(ActionCheck(True))

    return RejectionDecision(
        ActionCheck(False, f"DedupEngine: can not cancel with deduplication set in state={state!r}.")
    )


def check_biometric_clean(operation: RdpOperation) -> ActionCheck:
    """Check that the biometric DedupEngine set can back a clean replacement RDP."""
    if operation.status != RdpOperation.Status.SUCCESS:
        return ActionCheck(False, "RDP: successful biometric deduplication is required.")

    if (state := _remote_state(operation)) != DeduplicationSetState.DEDUPLICATED:
        return ActionCheck(False, f"DedupEngine: can not create clean RDP with deduplication set in state={state!r}.")

    return ActionCheck(True)


def reject_biometric_set(operation: RdpOperation) -> None:
    """Reject the biometric DedupEngine set of a cancelled RDP unless it is already gone."""
    try:
        state = _remote_state(operation)
        if state in REJECTABLE_DEDUPLICATION_SET_STATES:
            reject_deduplication_set(
                operation_id=operation.id,
                group_reference_id=operation.rdp.program.unicef_id,
            )
        elif state not in {None, DeduplicationSetState.REJECTED}:
            raise RdpWorkflowError({"errors": [f"DedupEngine: can not reject deduplication set in state={state!r}."]})
    except (RemoteError, RemoteUnavailableError) as exc:
        raise RdpWorkflowError({"errors": [str(exc)]}) from exc


def approve_biometric_set(operation: RdpOperation) -> None:
    """Approve the biometric DedupEngine set after a successful HOPE push."""
    approve_deduplication_set_after_successful_push(
        operation_id=operation.id,
        group_reference_id=operation.rdp.program.unicef_id,
    )
