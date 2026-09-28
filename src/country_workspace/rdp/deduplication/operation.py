from typing import TYPE_CHECKING
from uuid import UUID

from country_workspace.contrib.dedup_engine import make_dedup_client
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.rdp.operations.repository import append_rdp_operation_log

from .types import DeduplicationLogAction

if TYPE_CHECKING:
    from country_workspace.rdp.types import OperationLogResult


def reject_deduplication_set(*, group_reference_id: str, deduplication_set_id: str) -> None:
    """Reject a Dedup Engine deduplication set."""
    with make_dedup_client(group_reference_id, deduplication_set_id=deduplication_set_id) as client:
        client.reject()


def approve_deduplication_set_after_successful_push(
    *,
    operation_id: UUID | None,
    group_reference_id: str,
) -> None:
    """Approve and record the biometric operation after a successful HOPE push."""
    if operation_id is None:
        return

    deduplication_set_id = str(operation_id)
    result: OperationLogResult
    try:
        with make_dedup_client(group_reference_id, deduplication_set_id=deduplication_set_id) as client:
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
