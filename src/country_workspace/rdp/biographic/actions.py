from typing import TYPE_CHECKING
from uuid import UUID

from country_workspace.contrib.biographic_dedup import make_biographic_client
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.rdp.deduplication.types import DeduplicationLogAction
from country_workspace.rdp.operations.repository import append_rdp_operation_log, get_rdp_operation

if TYPE_CHECKING:
    from country_workspace.rdp.types import OperationLogResult


def approve_biographic_set_after_successful_push(*, operation_id: UUID | None) -> None:
    """Approve and record the biographic operation after a successful HOPE push.

    Approval turns the pushed individuals into the population later RDPs are checked against.
    """
    if operation_id is None:
        return

    result: OperationLogResult
    try:
        operation = get_rdp_operation(pk=operation_id)
        if not operation.external_id:
            return
        with make_biographic_client(operation.rdp.program, dataset_id=operation.external_id) as client:
            client.approve()
    except (RemoteError, RemoteUnavailableError) as exc:
        result = {"success": False, "error": str(exc)}
    else:
        result = {"success": True}

    append_rdp_operation_log(
        operation_id=operation_id,
        action=DeduplicationLogAction.APPROVE_SET,
        result=result,
    )


def reject_biographic_set(*, operation_id: UUID) -> None:
    """Reject and record the biographic set of an operation.

    A rejected set is never matched against again.
    """
    try:
        operation = get_rdp_operation(pk=operation_id)
        with make_biographic_client(operation.rdp.program, dataset_id=operation.external_id) as client:
            client.reject()
    except (RemoteError, RemoteUnavailableError) as exc:
        append_rdp_operation_log(
            operation_id=operation_id,
            action=DeduplicationLogAction.REJECT_SET,
            result={"success": False, "error": str(exc)},
        )
        raise

    append_rdp_operation_log(
        operation_id=operation_id,
        action=DeduplicationLogAction.REJECT_SET,
        result={"success": True},
    )
