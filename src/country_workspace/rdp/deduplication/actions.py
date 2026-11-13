from collections.abc import Callable
from typing import TYPE_CHECKING

from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import RdpOperation
from country_workspace.rdp.operations.repository import append_rdp_operation_log

from .types import DeduplicationLogAction


if TYPE_CHECKING:
    from country_workspace.rdp.types import OperationLogResult


def approve_remote_set_after_successful_push(operation: RdpOperation, approve: Callable[[RdpOperation], None]) -> None:
    """Approve the remote set of an operation after a successful HOPE push and record the outcome.

    A failure is only recorded: the push already succeeded, so it must not be reported as failed.
    """
    result: OperationLogResult
    try:
        approve(operation)
    except (RemoteError, RemoteUnavailableError) as exc:
        result = {"success": False, "error": str(exc)}
    else:
        result = {"success": True}

    append_rdp_operation_log(
        operation_id=operation.id,
        action=DeduplicationLogAction.APPROVE_SET,
        result=result,
    )


def reject_remote_set(operation: RdpOperation, reject: Callable[[RdpOperation], None]) -> None:
    """Reject the remote set of an operation and record the outcome. A failure is recorded and re-raised."""
    try:
        reject(operation)
    except (RemoteError, RemoteUnavailableError) as exc:
        append_rdp_operation_log(
            operation_id=operation.id,
            action=DeduplicationLogAction.REJECT_SET,
            result={"success": False, "error": str(exc)},
        )
        raise

    append_rdp_operation_log(
        operation_id=operation.id,
        action=DeduplicationLogAction.REJECT_SET,
        result={"success": True},
    )
