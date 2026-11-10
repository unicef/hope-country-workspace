from typing import TYPE_CHECKING

from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import RdpOperation
from country_workspace.rdp.operations.repository import append_rdp_operation_log

from ..types import DeduplicationLogAction
from .remote import make_operation_client


if TYPE_CHECKING:
    from country_workspace.rdp.types import OperationLogResult


def approve_biographic_dataset_after_successful_push(operation: RdpOperation) -> None:
    """Approve and record the biographic dataset after a successful HOPE push.

    Approval turns the pushed individuals into the population later RDPs are checked against.
    """
    if not operation.external_id:
        return

    result: OperationLogResult
    try:
        with make_operation_client(operation) as client:
            client.approve()
    except (RemoteError, RemoteUnavailableError) as exc:
        result = {"success": False, "error": str(exc)}
    else:
        result = {"success": True}

    append_rdp_operation_log(
        operation_id=operation.id,
        action=DeduplicationLogAction.APPROVE_SET,
        result=result,
    )


def reject_biographic_dataset(operation: RdpOperation) -> None:
    """Reject and record the biographic dataset of an operation.

    A rejected dataset is never matched against again.
    """
    try:
        with make_operation_client(operation) as client:
            client.reject()
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
