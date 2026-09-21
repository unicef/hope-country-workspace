from typing import Any, TYPE_CHECKING
from strategy_field.utils import fqn
from django.db import IntegrityError, transaction

from country_workspace.contrib.dedup_engine import (
    REJECTABLE_DEDUPLICATION_SET_STATES,
    DeduplicationSetState,
    make_dedup_client,
)
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import AsyncJob, Program, Rdp
from country_workspace.models.rdp import RdpOperationAction
from country_workspace.rdp.deduplication.operations import reject_deduplication_set
from country_workspace.rdp.deduplication.policy import get_deduplication_policy
from .exceptions import RdpWorkflowError
from .policy import ActionCheck, get_rdp_policy
from .repository import (
    append_rdp_operation_log,
    lock_rdp_for_update,
    set_rdp_beneficiaries_removed,
)
from .validation import preflight_errors


if TYPE_CHECKING:
    from .types import CreateRdpConfig


def create_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Create an RDP for the selected beneficiaries after passing preflight checks."""
    if job.program.beneficiary_group is None:
        raise RdpWorkflowError({"errors": ["RDP: beneficiary_group is not set"]})

    config: CreateRdpConfig = job.config
    errors = preflight_errors(pks=config["pks"], master_detail=config["master_detail"], exclude_rdp_ids=())
    if errors:
        raise RdpWorkflowError({"errors": errors})

    if job.program.biometric_deduplication_enabled:
        try:
            with make_dedup_client(job.program.unicef_id) as client:
                if not client.can_create_deduplication_set():
                    raise RdpWorkflowError(
                        {"errors": ["DedupEngine: can not create deduplication set for this program."]}
                    )
        except (RemoteError, RemoteUnavailableError) as e:
            raise RdpWorkflowError({"errors": [str(e)]}) from e

    try:
        with transaction.atomic():
            Program.objects.select_for_update().get(pk=config["program_id"])
            rdp = Rdp.objects.create(
                country_office_id=config["country_office_id"],
                program_id=config["program_id"],
                name=config["batch_name"],
                pushed_by_id=config["pushed_by_id"],
                status=Rdp.PushStatus.PENDING,
            )
            rdp.add_beneficiaries(config["pks"], config["master_detail"])
            AsyncJob.objects.filter(id=job.id).update(rdp=rdp)
    except IntegrityError as e:
        message = "RDP: can not create record"
        if "uniq_non_terminal_rdp_per_program" in str(e):
            message = "RDP: can not create while another RDP is unfinished"
        raise RdpWorkflowError({"errors": [message]}) from e

    return {"rdp_id": rdp.id}


def reset_rdp(*, rdp_id: int) -> ActionCheck:
    """Reset the latest successful RDP."""
    with transaction.atomic():
        rdp = lock_rdp_for_update(pk=rdp_id)
        check = get_rdp_policy(rdp).reset_check()
        if not check.allowed:
            return check

        set_rdp_beneficiaries_removed(rdp=rdp, removed=False)
        rdp.mark_cancelled()

    return ActionCheck(True)


def reject_cancelled_rdp_set_core(job: AsyncJob) -> dict[str, Any]:
    """Reject the DedupEngine set belonging to a cancelled RDP."""
    rdp = Rdp.objects.select_related("program").get(pk=job.config["rdp_id"])
    deduplication_set_id = job.config["deduplication_set_id"]

    if rdp.status != Rdp.PushStatus.CANCELLED or str(rdp.deduplication_set_id) != deduplication_set_id:
        raise RdpWorkflowError({"errors": ["RDP: this cancellation job is no longer current."]})

    try:
        state = get_deduplication_policy(rdp).deduplication_set_state
        if state in REJECTABLE_DEDUPLICATION_SET_STATES:
            reject_deduplication_set(
                group_reference_id=rdp.program.unicef_id,
                deduplication_set_id=deduplication_set_id,
            )
        elif state != DeduplicationSetState.REJECTED:
            raise RdpWorkflowError({"errors": [f"DedupEngine: can not reject deduplication set in state={state!r}."]})
    except (RemoteError, RemoteUnavailableError) as exc:
        raise RdpWorkflowError({"errors": [str(exc)]}) from exc

    return {"rdp_id": rdp.pk, "deduplication_set_rejected": True}


def claim_rdp_cancel(rdp_id: int, *, user_id: int) -> tuple[ActionCheck, bool]:
    """Cancel an RDP and schedule DedupEngine cleanup when required."""
    rdp = Rdp.objects.select_related("program").get(pk=rdp_id)
    policy = get_deduplication_policy(rdp)
    if not (check := policy.cancel_check()).allowed:
        return check, False

    needs_rejection = bool(
        rdp.deduplication_set_id and policy.deduplication_set_state in REJECTABLE_DEDUPLICATION_SET_STATES
    )

    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp_id)
        if not (check := get_rdp_policy(locked).cancel_check()).allowed:
            return check, False
        if locked.is_dedup_settings_locked:
            return ActionCheck(False, "RDP: can not cancel while deduplication is queued or running."), False
        if (
            locked.deduplication_set_id != rdp.deduplication_set_id
            or locked.deduplication_findings_count != rdp.deduplication_findings_count
        ):
            return ActionCheck(False, "RDP: deduplication result has changed. Please retry."), False

        was_review_pending = locked.status == Rdp.PushStatus.REVIEW_PENDING
        locked.mark_cancelled()

        if was_review_pending:
            append_rdp_operation_log(
                rdp=locked,
                action=RdpOperationAction.REVIEW_DECISION,
                result={
                    "decision": "CANCEL",
                    "user_id": str(user_id),
                    "outcome": Rdp.PushStatus.CANCELLED,
                    "deduplication_set_rejection": "queued" if needs_rejection else "not_required",
                },
            )

        if needs_rejection:
            job = AsyncJob.objects.create(
                description="Reject cancelled RDP deduplication set",
                type=AsyncJob.JobType.TASK,
                owner_id=user_id,
                action=fqn(reject_cancelled_rdp_set_core),
                program_id=locked.program_id,
                rdp=locked,
                config={
                    "rdp_id": locked.pk,
                    "deduplication_set_id": str(locked.deduplication_set_id),
                },
            )
            transaction.on_commit(job.queue)

    return ActionCheck(True), needs_rejection


def cancel_existing_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Handle a previously queued RDP cancellation job."""
    if job.owner_id is None:
        raise RdpWorkflowError({"errors": ["RDP: cancellation job owner is not set."]})

    rdp_id = job.config["rdp_id"]
    check, rejection_queued = claim_rdp_cancel(rdp_id=rdp_id, user_id=job.owner_id)
    check.require()
    return {"rdp_id": rdp_id, "deduplication_set_rejection_queued": rejection_queued}
