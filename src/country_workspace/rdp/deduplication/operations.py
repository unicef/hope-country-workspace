from typing import TYPE_CHECKING

from uuid import UUID

from django.db import transaction

from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.contrib.dedup_engine import make_dedup_client
from country_workspace.models.rdp import RdpOperationAction
from country_workspace.rdp.repository import lock_rdp_for_update, append_rdp_operation_log

if TYPE_CHECKING:
    from country_workspace.rdp.types import OperationLogResult


def approve_deduplication_set_after_successful_push(
    *,
    rdp_id: int,
    job_id: int,
    group_reference_id: str,
    deduplication_set_id: UUID | None,
) -> None:
    """Approve and record the active DedupEngine set after a successful HOPE push."""
    if not deduplication_set_id:
        return

    ds_id = str(deduplication_set_id)
    result: OperationLogResult
    try:
        with make_dedup_client(group_reference_id, deduplication_set_id=ds_id) as client:
            client.approve()
    except (RemoteError, RemoteUnavailableError) as exc:
        result = {"deduplication_set_id": ds_id, "success": False, "error": str(exc)}
    else:
        result = {"deduplication_set_id": ds_id, "success": True}

    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp_id)
        append_rdp_operation_log(
            rdp=locked,
            action=RdpOperationAction.APPROVE_DEDUPLICATION_SET,
            job_id=job_id,
            result=result,
        )


def reject_deduplication_set(*, group_reference_id: str, deduplication_set_id: str) -> None:
    """Reject a Dedup Engine deduplication set."""
    with make_dedup_client(group_reference_id, deduplication_set_id=deduplication_set_id) as client:
        client.reject()
