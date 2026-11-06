from typing import Any

from django.db import transaction

from country_workspace.contrib.dedup_engine import (
    NON_BLOCKING_DEDUPLICATION_SET_STATES,
    REJECTABLE_DEDUPLICATION_SET_STATES,
    retrieve_deduplication_set_state,
)
from country_workspace.models import AsyncJob, Rdp
from country_workspace.models.rdp import RdpLogEntryType

from country_workspace.rdp.deduplication.repository import biometric_operation_for_rdp
from country_workspace.rdp.deduplication.workflow import schedule_cancelled_rdp_set_rejection
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.policy import ActionCheck, get_rdp_policy
from country_workspace.rdp.repository import append_rdp_log, lock_rdp_for_update


def _biometric_rejection_check(rdp: Rdp) -> tuple[ActionCheck, str | None]:
    """Check whether the biometric DedupEngine set must be rejected on cancellation."""
    if (operation := biometric_operation_for_rdp(rdp=rdp)) is None:
        return ActionCheck(True), None

    deduplication_set_id = str(operation.id)
    state = retrieve_deduplication_set_state(
        group_reference_id=rdp.program.unicef_id,
        deduplication_set_id=deduplication_set_id,
    )

    if state in REJECTABLE_DEDUPLICATION_SET_STATES:
        return ActionCheck(True), deduplication_set_id
    if state is None or state in NON_BLOCKING_DEDUPLICATION_SET_STATES:
        return ActionCheck(True), None

    return (
        ActionCheck(False, f"DedupEngine: can not cancel with deduplication set in state={state!r}."),
        None,
    )


def cancel_rdp(rdp_id: int, *, user_id: int) -> tuple[ActionCheck, bool]:
    """Cancel an RDP and schedule DedupEngine cleanup when required."""
    rdp = Rdp.objects.select_related("program").get(pk=rdp_id)

    if not (check := get_rdp_policy(rdp).cancel_check()).allowed:
        return check, False

    rejection_set_id = None
    if not rdp.program.cleanup_in_progress:
        rejection_check, rejection_set_id = _biometric_rejection_check(rdp)
        if not rejection_check.allowed:
            return rejection_check, False

    with transaction.atomic():
        rdp = lock_rdp_for_update(pk=rdp_id)

        if not (check := get_rdp_policy(rdp).cancel_check()).allowed:
            return check, False

        if rdp.program.cleanup_in_progress:
            rejection_set_id = None

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
                    "deduplication_set_rejection": "scheduled" if rejection_set_id else "not_required",
                },
            )

        if rejection_set_id:
            schedule_cancelled_rdp_set_rejection(
                rdp=rdp,
                user_id=user_id,
                deduplication_set_id=rejection_set_id,
            )

    return ActionCheck(True), rejection_set_id is not None


def cancel_existing_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Handle a previously queued RDP cancellation job."""
    if job.owner_id is None:
        raise RdpWorkflowError({"errors": ["RDP: cancellation job owner is not set."]})

    rdp_id = job.config["rdp_id"]
    check, rejection_scheduled = cancel_rdp(rdp_id=rdp_id, user_id=job.owner_id)
    check.require()
    return {"rdp_id": rdp_id, "deduplication_set_rejection_scheduled": rejection_scheduled}
