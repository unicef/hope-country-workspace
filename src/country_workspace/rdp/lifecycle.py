from typing import Any

from django.db import IntegrityError, transaction

from country_workspace.contrib.dedup_engine import (
    NON_BLOCKING_DEDUPLICATION_SET_STATES,
    REJECTABLE_DEDUPLICATION_SET_STATES,
    DeduplicationSetState,
    retrieve_deduplication_set_state,
)
from country_workspace.models import AsyncJob, Program, Rdp, RdpOperation
from country_workspace.models.rdp import RdpLogEntryType
from .deduplication.repository import (
    biometric_clean_rdp_selection,
    biometric_operation_for_rdp,
)
from .deduplication.workflow import schedule_cancelled_rdp_set_rejection
from .deduplication.types import ThresholdType
from .exceptions import RdpWorkflowError
from .operations.workflow import schedule_rdp_operations
from .policy import ActionCheck, get_rdp_policy
from .push.workflow import schedule_rdp_push_evaluation
from .repository import (
    append_rdp_log,
    create_rdp,
    lock_rdp_for_update,
    set_rdp_beneficiaries_removed,
)
from .validation import preflight_errors
from .types import CreateRdpConfig, CreateRdpOperationConfig, JSONValue


def _validate_rdp_creation(*, program: Program, config: CreateRdpConfig, exclude_rdp_ids: tuple[int, ...] = ()) -> None:
    """Validate a selection before creating an RDP."""
    if program.beneficiary_group is None:
        raise RdpWorkflowError({"errors": ["RDP: beneficiary_group is not set"]})
    if errors := preflight_errors(
        pks=config["pks"], master_detail=config["master_detail"], exclude_rdp_ids=exclude_rdp_ids
    ):
        raise RdpWorkflowError({"errors": errors})


def _rdp_creation_error(exc: IntegrityError) -> RdpWorkflowError:
    """Convert an RDP creation integrity error to a workflow error."""
    message = (
        "RDP: can not create while another RDP is unfinished"
        if "uniq_non_terminal_rdp_per_program" in str(exc)
        else "RDP: can not create record"
    )
    return RdpWorkflowError({"errors": [message]})


def create_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Create an RDP and schedule its processing."""
    config: CreateRdpConfig = job.config
    _validate_rdp_creation(program=job.program, config=config)

    try:
        with transaction.atomic():
            Program.objects.select_for_update().get(pk=config["program_id"])
            rdp = create_rdp(config=config)
            AsyncJob.objects.filter(id=job.id).update(rdp=rdp)
            _schedule_rdp_processing(rdp=rdp)
    except IntegrityError as exc:
        raise _rdp_creation_error(exc) from exc

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


def _schedule_rdp_processing(*, rdp: Rdp) -> None:
    """Schedule RDP operations or push evaluation when none are configured."""
    if rdp.operations.exists():
        schedule_rdp_operations(rdp=rdp)
    else:
        schedule_rdp_push_evaluation(rdp=rdp)


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

    rejection_check, rejection_set_id = _biometric_rejection_check(rdp)
    if not rejection_check.allowed:
        return rejection_check, False

    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp_id)

        if not (check := get_rdp_policy(locked).cancel_check()).allowed:
            return check, False

        was_review_pending = locked.status == Rdp.PushStatus.REVIEW_PENDING
        locked.mark_cancelled()

        if was_review_pending:
            append_rdp_log(
                rdp=locked,
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
                rdp=locked,
                user_id=user_id,
                deduplication_set_id=rejection_set_id,
            )

    return ActionCheck(True), rejection_set_id is not None


def _clean_rdp_check(rdp: Rdp) -> tuple[ActionCheck, RdpOperation | None]:
    """Check Clean RDP prerequisites and return its biometric operation."""
    if rdp.status != Rdp.PushStatus.REVIEW_PENDING:
        return ActionCheck(False, f"RDP: can not create clean RDP in status={rdp.status}"), None

    operation = biometric_operation_for_rdp(rdp=rdp)
    if operation is None or operation.status != RdpOperation.Status.SUCCESS:
        return ActionCheck(False, "RDP: successful biometric deduplication is required."), None

    state = retrieve_deduplication_set_state(
        group_reference_id=rdp.program.unicef_id,
        deduplication_set_id=str(operation.id),
    )
    if state != DeduplicationSetState.DEDUPLICATED:
        return ActionCheck(
            False, f"DedupEngine: can not create clean RDP with deduplication set in state={state!r}."
        ), None

    return ActionCheck(True), operation


def _clean_rdp_operation_configs(rdp: Rdp) -> list[CreateRdpOperationConfig]:
    """Return operation configs for a clean replacement RDP."""
    configs: list[CreateRdpOperationConfig] = []
    for operation in rdp.operations.order_by("operation_type"):
        config: dict[str, JSONValue] = dict(operation.config)
        if operation.operation_type == RdpOperation.Type.BIOMETRIC_DEDUPLICATION:
            config.update(threshold_type=ThresholdType.COUNT.value, threshold_value="0")
        configs.append(
            {
                "operation_type": operation.operation_type,
                "config": config,
            }
        )
    return configs


def create_clean_rdp(rdp_id: int, *, user_id: int) -> tuple[ActionCheck, Rdp | None]:
    """Replace a reviewed RDP with a clean pending RDP and schedule old-set rejection."""
    rdp = Rdp.objects.select_related("program__beneficiary_group", "program__country_office").get(pk=rdp_id)

    check, operation = _clean_rdp_check(rdp)
    if not check.allowed or operation is None:
        return check, None

    master_detail, pks = biometric_clean_rdp_selection(operation=operation)
    if not pks:
        return ActionCheck(False, "RDP: no beneficiaries remain after removing biometric findings."), None

    try:
        with transaction.atomic():
            Program.objects.select_for_update().get(pk=rdp.program_id)
            rdp = lock_rdp_for_update(pk=rdp_id)

            if rdp.status != Rdp.PushStatus.REVIEW_PENDING:
                return ActionCheck(False, f"RDP: can not create clean RDP in status={rdp.status}"), None

            operation = biometric_operation_for_rdp(rdp=rdp)
            if (
                operation is None
                or operation.status != RdpOperation.Status.SUCCESS
                or biometric_clean_rdp_selection(operation=operation) != (master_detail, pks)
            ):
                return ActionCheck(False, "RDP: biometric result or selection has changed. Please retry."), None

            config: CreateRdpConfig = {
                "batch_name": f"{(rdp.name or str(rdp))[:249]} clean",
                "country_office_id": rdp.country_office_id,
                "program_id": rdp.program_id,
                "pushed_by_id": user_id,
                "master_detail": master_detail,
                "pks": pks,
                "operations": _clean_rdp_operation_configs(rdp),
            }

            _validate_rdp_creation(program=rdp.program, config=config, exclude_rdp_ids=(rdp_id,))
            rdp.mark_cancelled()
            clean_rdp = create_rdp(config=config)

            job = schedule_cancelled_rdp_set_rejection(
                rdp=rdp,
                user_id=user_id,
                deduplication_set_id=str(operation.id),
                clean_rdp_id=clean_rdp.pk,
            )
            append_rdp_log(
                rdp=rdp,
                entry_type=RdpLogEntryType.REVIEW_DECISION,
                result={
                    "decision": "PUSH_CLEAN",
                    "user_id": str(user_id),
                    "new_rdp_id": clean_rdp.pk,
                    "deduplication_set_rejection": "scheduled",
                    "rejection_job_id": job.pk,
                },
            )
    except IntegrityError as exc:
        raise _rdp_creation_error(exc) from exc

    return ActionCheck(True), clean_rdp


def cancel_existing_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Handle a previously queued RDP cancellation job."""
    if job.owner_id is None:
        raise RdpWorkflowError({"errors": ["RDP: cancellation job owner is not set."]})

    rdp_id = job.config["rdp_id"]
    check, rejection_scheduled = cancel_rdp(rdp_id=rdp_id, user_id=job.owner_id)
    check.require()
    return {"rdp_id": rdp_id, "deduplication_set_rejection_scheduled": rejection_scheduled}
