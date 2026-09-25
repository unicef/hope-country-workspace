from typing import Any, TYPE_CHECKING
from strategy_field.utils import fqn
from django.db import IntegrityError, transaction

from country_workspace.contrib.dedup_engine import (
    NON_BLOCKING_DEDUPLICATION_SET_STATES,
    REJECTABLE_DEDUPLICATION_SET_STATES,
    DeduplicationSetState,
    retrieve_deduplication_set_state,
)
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import AsyncJob, Program, Rdp, RdpOperation
from country_workspace.models.rdp import RdpOperationAction
from country_workspace.rdp.deduplication.operations import reject_deduplication_set
from country_workspace.rdp.deduplication.policy import get_deduplication_policy
from .exceptions import RdpWorkflowError
from .operation import schedule_rdp_operation
from .policy import ActionCheck, get_rdp_policy
from .repository import (
    append_rdp_operation_log,
    clean_rdp_selection,
    lock_rdp_for_update,
    set_rdp_beneficiaries_removed,
)
from .validation import preflight_errors

if TYPE_CHECKING:
    from .types import CreateRdpConfig


def _validate_rdp_creation(*, program: Program, config: CreateRdpConfig, exclude_rdp_ids: tuple[int, ...] = ()) -> None:
    """Validate a selection before creating an RDP."""
    if program.beneficiary_group is None:
        raise RdpWorkflowError({"errors": ["RDP: beneficiary_group is not set"]})
    if errors := preflight_errors(
        pks=config["pks"], master_detail=config["master_detail"], exclude_rdp_ids=exclude_rdp_ids
    ):
        raise RdpWorkflowError({"errors": errors})


def _create_rdp(*, config: CreateRdpConfig) -> Rdp:
    """Create a pending RDP with beneficiaries and configured operations."""
    rdp = Rdp.objects.create(
        country_office_id=config["country_office_id"],
        program_id=config["program_id"],
        name=config["batch_name"],
        pushed_by_id=config["pushed_by_id"],
        status=Rdp.PushStatus.PENDING,
    )
    rdp.add_beneficiaries(config["pks"], config["master_detail"])
    for operation in config["operations"]:
        rdp.operations.create(
            operation_type=operation["operation_type"],
            config=operation["config"],
        )
    return rdp


def create_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Create an RDP and schedule its configured operations."""
    config: CreateRdpConfig = job.config
    _validate_rdp_creation(program=job.program, config=config)

    try:
        with transaction.atomic():
            Program.objects.select_for_update().get(pk=config["program_id"])
            rdp = _create_rdp(config=config)
            AsyncJob.objects.filter(id=job.id).update(rdp=rdp)

            for operation in rdp.operations.all():
                schedule_rdp_operation(operation=operation, owner_id=config["pushed_by_id"])

    except IntegrityError as exc:
        message = "RDP: can not create record"
        if "uniq_non_terminal_rdp_per_program" in str(exc):
            message = "RDP: can not create while another RDP is unfinished"
        raise RdpWorkflowError({"errors": [message]}) from exc

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

    belongs_to_rdp = (
        str(rdp.deduplication_set_id) == deduplication_set_id
        or rdp.operations.filter(
            pk=deduplication_set_id,
            operation_type=RdpOperation.Type.BIOMETRIC_DEDUPLICATION,
        ).exists()
    )
    if rdp.status != Rdp.PushStatus.CANCELLED or not belongs_to_rdp:
        raise RdpWorkflowError({"errors": ["RDP: this cancellation job is no longer current."]})

    try:
        state = retrieve_deduplication_set_state(
            group_reference_id=rdp.program.unicef_id,
            deduplication_set_id=deduplication_set_id,
        )
        if state in REJECTABLE_DEDUPLICATION_SET_STATES:
            reject_deduplication_set(
                group_reference_id=rdp.program.unicef_id,
                deduplication_set_id=deduplication_set_id,
            )
        elif state not in {None, DeduplicationSetState.REJECTED}:
            raise RdpWorkflowError({"errors": [f"DedupEngine: can not reject deduplication set in state={state!r}."]})
    except (RemoteError, RemoteUnavailableError) as exc:
        raise RdpWorkflowError({"errors": [str(exc)]}) from exc

    return {"rdp_id": rdp.pk, "deduplication_set_rejected": True}


def _schedule_rejection_job(*, rdp: Rdp, user_id: int, deduplication_set_id: str) -> AsyncJob:
    """Create and queue a DedupEngine rejection job after commit."""
    job = AsyncJob.objects.create(
        description="Reject cancelled RDP deduplication set",
        type=AsyncJob.JobType.TASK,
        owner_id=user_id,
        action=fqn(reject_cancelled_rdp_set_core),
        program_id=rdp.program_id,
        rdp=rdp,
        config={"rdp_id": rdp.pk, "deduplication_set_id": deduplication_set_id},
    )
    transaction.on_commit(job.queue)
    return job


def _deduplication_rejection_check(rdp: Rdp) -> tuple[ActionCheck, str | None]:
    """Check whether the RDP DedupEngine set must be rejected on cancellation."""
    operation = rdp.operations.filter(
        operation_type=RdpOperation.Type.BIOMETRIC_DEDUPLICATION,
    ).first()
    deduplication_set_id = str(operation.id) if operation else None

    if deduplication_set_id is None and rdp.deduplication_set_id:
        deduplication_set_id = str(rdp.deduplication_set_id)

    if deduplication_set_id is None:
        return ActionCheck(True), None

    state = retrieve_deduplication_set_state(
        group_reference_id=rdp.program.unicef_id,
        deduplication_set_id=deduplication_set_id,
    )
    if state == DeduplicationSetState.DEDUPLICATED:
        return ActionCheck(True), deduplication_set_id
    if state is None or state in NON_BLOCKING_DEDUPLICATION_SET_STATES:
        return ActionCheck(True), None

    return (
        ActionCheck(False, f"DedupEngine: can not cancel with deduplication set in state={state!r}."),
        None,
    )


def claim_rdp_cancel(rdp_id: int, *, user_id: int) -> tuple[ActionCheck, bool]:
    """Cancel an RDP and schedule DedupEngine cleanup when required."""
    rdp = Rdp.objects.select_related("program").get(pk=rdp_id)

    if not (check := get_rdp_policy(rdp).cancel_check()).allowed:
        return check, False

    rejection_check, rejection_set_id = _deduplication_rejection_check(rdp)
    if not rejection_check.allowed:
        return rejection_check, False

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
                    "deduplication_set_rejection": "queued" if rejection_set_id else "not_required",
                },
            )

        if rejection_set_id:
            _schedule_rejection_job(
                rdp=locked,
                user_id=user_id,
                deduplication_set_id=rejection_set_id,
            )

    return ActionCheck(True), rejection_set_id is not None


def _check_push_clean_preconditions(rdp: Rdp) -> ActionCheck:
    """Check prerequisites for Push Clean."""
    if rdp.status != Rdp.PushStatus.REVIEW_PENDING:
        return ActionCheck(False, f"RDP: can not push clean in status={rdp.status}")
    if rdp.is_dedup_settings_locked or not rdp.deduplication_set_id or rdp.deduplication_findings_count is None:
        return ActionCheck(False, "RDP: completed deduplication result is required.")
    if not rdp.program.biometric_deduplication_enabled:
        return ActionCheck(False, "DedupEngine: biometric deduplication is not enabled for this program.")
    if (state := get_deduplication_policy(rdp).deduplication_set_state) != DeduplicationSetState.DEDUPLICATED:
        return ActionCheck(False, f"DedupEngine: can not push clean with deduplication set in state={state!r}.")
    return ActionCheck(True)


def claim_rdp_push_clean(rdp_id: int, *, user_id: int) -> tuple[ActionCheck, Rdp | None]:
    """Replace a reviewed RDP with a clean pending RDP and queue old-set rejection."""
    rdp = Rdp.objects.select_related("program__beneficiary_group", "program__country_office").get(pk=rdp_id)
    if not (check := _check_push_clean_preconditions(rdp)).allowed:
        return check, None

    master_detail, pks = clean_rdp_selection(rdp=rdp)
    if not pks:
        return ActionCheck(False, "RDP: no beneficiaries remain after removing duplicates."), None

    config: CreateRdpConfig = {
        "batch_name": f"{(rdp.name or str(rdp))[:249]} clean",
        "country_office_id": rdp.country_office_id,
        "program_id": rdp.program_id,
        "pushed_by_id": user_id,
        "master_detail": master_detail,
        "pks": pks,
        "operations": [],
    }
    try:
        with transaction.atomic():
            Program.objects.select_for_update().get(pk=rdp.program_id)
            locked = lock_rdp_for_update(pk=rdp_id)
            if locked.status != Rdp.PushStatus.REVIEW_PENDING:
                return ActionCheck(False, f"RDP: can not push clean in status={locked.status}"), None
            if (
                locked.is_dedup_settings_locked
                or not locked.program.biometric_deduplication_enabled
                or locked.deduplication_set_id != rdp.deduplication_set_id
                or locked.deduplication_findings_count != rdp.deduplication_findings_count
                or clean_rdp_selection(rdp=locked) != (master_detail, pks)
            ):
                return ActionCheck(False, "RDP: deduplication result or selection has changed. Please retry."), None

            _validate_rdp_creation(program=locked.program, config=config, exclude_rdp_ids=(rdp_id,))
            locked.mark_cancelled()
            clean_rdp = _create_rdp(config=config)
            job = _schedule_rejection_job(
                rdp=locked, user_id=user_id, deduplication_set_id=str(locked.deduplication_set_id)
            )
            append_rdp_operation_log(
                rdp=locked,
                action=RdpOperationAction.REVIEW_DECISION,
                result={
                    "decision": "PUSH_CLEAN",
                    "user_id": str(user_id),
                    "new_rdp_id": clean_rdp.pk,
                    "deduplication_set_rejection": "queued",
                    "rejection_job_id": job.pk,
                },
            )
    except IntegrityError as exc:
        message = "RDP: can not create record"
        if "uniq_non_terminal_rdp_per_program" in str(exc):
            message = "RDP: can not create while another RDP is unfinished"
        raise RdpWorkflowError({"errors": [message]}) from exc

    return ActionCheck(True), clean_rdp


def cancel_existing_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Handle a previously queued RDP cancellation job."""
    if job.owner_id is None:
        raise RdpWorkflowError({"errors": ["RDP: cancellation job owner is not set."]})

    rdp_id = job.config["rdp_id"]
    check, rejection_queued = claim_rdp_cancel(rdp_id=rdp_id, user_id=job.owner_id)
    check.require()
    return {"rdp_id": rdp_id, "deduplication_set_rejection_queued": rejection_queued}
