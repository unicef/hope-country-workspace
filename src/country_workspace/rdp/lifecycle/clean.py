from typing import NamedTuple
from uuid import UUID

from django.db import IntegrityError, transaction

from country_workspace.contrib.dedup_engine import DeduplicationSetState, retrieve_deduplication_set_state
from country_workspace.models import Program, Rdp, RdpOperation
from country_workspace.models.rdp import RdpLogEntryType

from country_workspace.rdp.deduplication.repository import biometric_operation_for_rdp
from country_workspace.rdp.deduplication.workflow import schedule_cancelled_rdp_set_rejection
from country_workspace.rdp.policy import ActionCheck
from country_workspace.rdp.push.thresholds import exceeded_operation_thresholds, threshold_findings_count_for_selection
from country_workspace.rdp.repository import append_rdp_log, clean_rdp_selection, create_rdp, lock_rdp_for_update
from country_workspace.rdp.types import (
    CreateRdpConfig,
    CreateRdpOperationConfig,
    JSONValue,
    OperationLogResult,
    ThresholdType,
)
from .creation import rdp_creation_error, schedule_rdp_processing, validate_rdp_creation


class _CleanRdpPlan(NamedTuple):
    biometric_operation_id: UUID | None
    exceeded_thresholds: dict[UUID, OperationLogResult]
    master_detail: bool
    pks: list[int]


def _clean_rdp_check(rdp: Rdp) -> tuple[ActionCheck, RdpOperation | None]:
    """Check Clean RDP prerequisites and return its biometric operation when configured."""
    if rdp.program.cleanup_in_progress:
        return ActionCheck(False, "Program cleanup is in progress."), None
    if rdp.status != Rdp.PushStatus.REVIEW_PENDING:
        return ActionCheck(False, f"RDP: can not create clean RDP in status={rdp.status}"), None

    operation = biometric_operation_for_rdp(rdp=rdp)
    if operation is None:
        return ActionCheck(True), None
    if operation.status != RdpOperation.Status.SUCCESS:
        return ActionCheck(False, "RDP: successful biometric deduplication is required."), None

    state = retrieve_deduplication_set_state(
        group_reference_id=rdp.program.unicef_id,
        deduplication_set_id=str(operation.id),
    )
    if state != DeduplicationSetState.DEDUPLICATED:
        return ActionCheck(
            False,
            f"DedupEngine: can not create clean RDP with deduplication set in state={state!r}.",
        ), None

    return ActionCheck(True), operation


def _prepare_clean_rdp_plan(
    *,
    rdp: Rdp,
    clean_operation_ids: set[UUID],
) -> tuple[ActionCheck, _CleanRdpPlan | None]:
    """Validate clean decisions and build the replacement plan."""
    check, biometric_operation = _clean_rdp_check(rdp)
    if not check.allowed:
        return check, None

    exceeded_thresholds = {operation.id: result for operation, result in exceeded_operation_thresholds(rdp=rdp)}
    if not clean_operation_ids:
        return ActionCheck(False, "RDP: select at least one operation to clean."), None
    if not clean_operation_ids <= set(exceeded_thresholds):
        return ActionCheck(False, "RDP: selected clean operations are no longer valid."), None

    master_detail, pks = clean_rdp_selection(rdp=rdp, operation_ids=clean_operation_ids)
    if not pks:
        return ActionCheck(False, "RDP: no beneficiaries remain after removing selected findings."), None

    return ActionCheck(True), _CleanRdpPlan(
        biometric_operation.id if biometric_operation else None,
        exceeded_thresholds,
        master_detail,
        pks,
    )


def _clean_rdp_plan_is_current(
    *,
    rdp: Rdp,
    clean_operation_ids: set[UUID],
    plan: _CleanRdpPlan,
    biometric_operation: RdpOperation | None,
) -> bool:
    """Return whether the reviewed results still match the clean plan."""
    if (biometric_operation.id if biometric_operation else None) != plan.biometric_operation_id or (
        biometric_operation is not None and biometric_operation.status != RdpOperation.Status.SUCCESS
    ):
        return False

    current_thresholds = {operation.id: result for operation, result in exceeded_operation_thresholds(rdp=rdp)}
    return current_thresholds == plan.exceeded_thresholds and clean_rdp_selection(
        rdp=rdp,
        operation_ids=clean_operation_ids,
    ) == (plan.master_detail, plan.pks)


def _clean_rdp_operation_configs(
    *,
    rdp: Rdp,
    clean_operation_ids: set[UUID],
    plan: _CleanRdpPlan,
) -> list[CreateRdpOperationConfig]:
    """Return operation configs for a clean replacement RDP."""
    configs: list[CreateRdpOperationConfig] = []

    for operation in rdp.operations.order_by("operation_type"):
        config: dict[str, JSONValue] = dict(operation.config)

        if operation.id in plan.exceeded_thresholds:
            threshold = (
                0
                if operation.id in clean_operation_ids
                else threshold_findings_count_for_selection(
                    operation=operation,
                    master_detail=plan.master_detail,
                    pks=plan.pks,
                )
            )
            config.update(
                threshold_type=ThresholdType.COUNT.value,
                threshold_value=str(threshold),
            )

        configs.append({"operation_type": operation.operation_type, "config": config})

    return configs


def _schedule_clean_rdp_processing(
    *,
    rdp: Rdp,
    clean_rdp: Rdp,
    user_id: int,
    biometric_operation: RdpOperation | None,
) -> dict[str, JSONValue]:
    """Schedule processing for a clean replacement RDP."""
    if biometric_operation is None:
        schedule_rdp_processing(rdp=clean_rdp)
        return {"deduplication_set_rejection": "not_required"}

    job = schedule_cancelled_rdp_set_rejection(
        rdp=rdp,
        user_id=user_id,
        deduplication_set_id=str(biometric_operation.id),
        clean_rdp_id=clean_rdp.pk,
    )
    return {
        "deduplication_set_rejection": "scheduled",
        "rejection_job_id": job.pk,
    }


def _create_clean_rdp_locked(
    *,
    source_rdp: Rdp,
    user_id: int,
    clean_operation_ids: set[UUID],
    plan: _CleanRdpPlan,
) -> tuple[ActionCheck, Rdp | None]:
    """Create a clean replacement after locking and revalidating the source RDP."""
    program = Program.objects.select_for_update().get(pk=source_rdp.program_id)
    if program.cleanup_in_progress:
        return ActionCheck(False, "Program cleanup is in progress."), None

    rdp = lock_rdp_for_update(pk=source_rdp.pk)
    if rdp.status != Rdp.PushStatus.REVIEW_PENDING:
        return ActionCheck(False, f"RDP: can not create clean RDP in status={rdp.status}"), None

    biometric_operation = biometric_operation_for_rdp(rdp=rdp)
    if not _clean_rdp_plan_is_current(
        rdp=rdp,
        clean_operation_ids=clean_operation_ids,
        plan=plan,
        biometric_operation=biometric_operation,
    ):
        return ActionCheck(False, "RDP: operation results or selection have changed. Please retry."), None

    config: CreateRdpConfig = {
        "batch_name": f"{(rdp.name or str(rdp))[:249]} clean",
        "country_office_id": rdp.country_office_id,
        "program_id": rdp.program_id,
        "pushed_by_id": user_id,
        "master_detail": plan.master_detail,
        "pks": plan.pks,
        "operations": _clean_rdp_operation_configs(
            rdp=rdp,
            clean_operation_ids=clean_operation_ids,
            plan=plan,
        ),
    }

    validate_rdp_creation(program=program, config=config, exclude_rdp_ids=(source_rdp.pk,))
    rdp.mark_cancelled()
    clean_rdp = create_rdp(config=config)

    rejection = _schedule_clean_rdp_processing(
        rdp=rdp,
        clean_rdp=clean_rdp,
        user_id=user_id,
        biometric_operation=biometric_operation,
    )
    exceeded_operation_ids = set(plan.exceeded_thresholds)
    append_rdp_log(
        rdp=rdp,
        entry_type=RdpLogEntryType.REVIEW_DECISION,
        result={
            "decision": "PUSH_CLEAN",
            "user_id": str(user_id),
            "new_rdp_id": clean_rdp.pk,
            "clean_operation_ids": sorted(map(str, clean_operation_ids)),
            "approved_operation_ids": sorted(map(str, exceeded_operation_ids - clean_operation_ids)),
            **rejection,
        },
    )
    return ActionCheck(True), clean_rdp


def create_clean_rdp(
    rdp_id: int,
    *,
    user_id: int,
    clean_operation_ids: set[UUID],
) -> tuple[ActionCheck, Rdp | None]:
    """Replace a reviewed RDP after applying selected operation finding decisions."""
    rdp = Rdp.objects.select_related("program__beneficiary_group", "program__country_office").get(pk=rdp_id)

    check, plan = _prepare_clean_rdp_plan(rdp=rdp, clean_operation_ids=clean_operation_ids)
    if plan is None:
        return check, None

    try:
        with transaction.atomic():
            return _create_clean_rdp_locked(
                source_rdp=rdp,
                user_id=user_id,
                clean_operation_ids=clean_operation_ids,
                plan=plan,
            )
    except IntegrityError as exc:
        raise rdp_creation_error(exc) from exc
