from typing import TYPE_CHECKING, Any

from django.db import transaction

from country_workspace.models import AsyncJob, Rdp
from country_workspace.models.rdp import RdpLogEntryType
from country_workspace.rdp.deduplication.workflow import (
    check_cancellation_rejections,
    schedule_cancelled_rdp_set_rejection,
)
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.policy import ActionCheck, get_rdp_policy
from country_workspace.rdp.repository import append_rdp_log, lock_rdp_for_update


if TYPE_CHECKING:
    from uuid import UUID


def cancel_rdp(rdp_id: int, *, user_id: int) -> tuple[ActionCheck, bool]:
    """Cancel an RDP and schedule DedupEngine cleanup when required."""
    rdp = Rdp.objects.select_related("program").get(pk=rdp_id)

    if not (check := get_rdp_policy(rdp).cancel_check()).allowed:
        return check, False

    rejection_operation_ids: tuple[UUID, ...] = ()
    if not rdp.program.cleanup_in_progress:
        rejection_check, rejection_operation_ids = check_cancellation_rejections(rdp)
        if not rejection_check.allowed:
            return rejection_check, False

    with transaction.atomic():
        rdp = lock_rdp_for_update(pk=rdp_id)

        if not (check := get_rdp_policy(rdp).cancel_check()).allowed:
            return check, False

        if rdp.program.cleanup_in_progress:
            rejection_operation_ids = ()

        was_review_pending = rdp.status == Rdp.PushStatus.REVIEW_PENDING
        rdp.mark_cancelled()

        if was_review_pending:
            append_rdp_log(
                rdp=rdp,
                entry_type=RdpLogEntryType.REVIEW_DECISION,
                result={
                    "decision": "CANCEL",
                    "user_id": str(user_id),
                    "outcome": Rdp.PushStatus.CANCELLED,
                    "deduplication_set_rejection": "scheduled" if rejection_operation_ids else "not_required",
                },
            )

        if rejection_operation_ids:
            schedule_cancelled_rdp_set_rejection(
                rdp=rdp,
                user_id=user_id,
                operation_ids=rejection_operation_ids,
            )

    return ActionCheck(True), bool(rejection_operation_ids)


def cancel_existing_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Handle a previously queued RDP cancellation job."""
    if job.owner_id is None:
        raise RdpWorkflowError({"errors": ["RDP: cancellation job owner is not set."]})

    rdp_id = job.config["rdp_id"]
    check, rejection_scheduled = cancel_rdp(rdp_id=rdp_id, user_id=job.owner_id)
    check.require()
    return {"rdp_id": rdp_id, "deduplication_set_rejection_scheduled": rejection_scheduled}
