from collections.abc import Iterable
from functools import partial
from typing import Any
from uuid import UUID

from django.db import transaction
from strategy_field.utils import fqn

from country_workspace.models import AsyncJob, Program, Rdp, RdpOperation
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.operations.repository import get_rdp_operation
from country_workspace.rdp.operations.workflow import schedule_rdp_operations
from country_workspace.rdp.policy import ActionCheck

from .registry import get_deduplication_backend, get_deduplication_backends


def deduplication_operations_for_rdp(rdp: Rdp) -> list[RdpOperation]:
    """Return the DedupEngine-backed operations of an RDP."""
    return list(
        rdp.operations.filter(operation_type__in=get_deduplication_backends())
        .select_related("rdp__program")
        .order_by("operation_type")
    )


def sync_deduplication_result(*, operation_id: UUID) -> bool:
    """Synchronize a DedupEngine-backed RDP operation."""
    try:
        operation = get_rdp_operation(pk=operation_id)
    except RdpOperation.DoesNotExist:
        return False

    if (backend := get_deduplication_backend(operation)) is None:
        return False
    return backend.sync(operation)


def check_cancellation_rejections(rdp: Rdp) -> tuple[ActionCheck, tuple[UUID, ...]]:
    """Check whether an RDP can be cancelled and return the operations whose remote sets must be rejected."""
    required: list[UUID] = []
    for operation in deduplication_operations_for_rdp(rdp):
        decision = get_deduplication_backends()[operation.operation_type].check_cancellation(operation)
        if not decision.check.allowed:
            return decision.check, ()
        if decision.required:
            required.append(operation.id)
    return ActionCheck(True), tuple(required)


def check_clean_rdp_deduplication(rdp: Rdp) -> tuple[ActionCheck, tuple[RdpOperation, ...]]:
    """Check that the remote sets of an RDP can back a clean replacement and return their operations."""
    operations = deduplication_operations_for_rdp(rdp)
    for operation in operations:
        if not (check := get_deduplication_backends()[operation.operation_type].check_clean(operation)).allowed:
            return check, ()
    return ActionCheck(True), tuple(operations)


def reject_cancelled_rdp_set_core(job: AsyncJob) -> dict[str, Any]:
    """Reject the remote sets of a cancelled RDP and continue its clean replacement when configured."""
    rdp = Rdp.objects.select_related("program").get(pk=job.config["rdp_id"])
    # Jobs queued before biographic deduplication carried a single `deduplication_set_id`.
    operation_ids = set(job.config.get("operation_ids") or [job.config["deduplication_set_id"]])
    operations = {str(operation.id): operation for operation in deduplication_operations_for_rdp(rdp)}

    if rdp.status != Rdp.PushStatus.CANCELLED or not operation_ids <= operations.keys():
        raise RdpWorkflowError({"errors": ["RDP: this cancellation job is no longer current."]})

    for operation_id in sorted(operation_ids):
        operation = operations[operation_id]
        get_deduplication_backends()[operation.operation_type].reject(operation)

    if clean_rdp_id := job.config.get("clean_rdp_id"):
        with transaction.atomic():
            program = Program.objects.select_for_update().only("cleanup_in_progress").get(pk=rdp.program_id)
            if program.cleanup_in_progress:
                return {"rdp_id": rdp.pk}
            clean_rdp = Rdp.objects.get(pk=clean_rdp_id, program_id=rdp.program_id)
            if clean_rdp.status != Rdp.PushStatus.PENDING:
                raise RdpWorkflowError({"errors": ["RDP: clean replacement is no longer pending."]})
            schedule_rdp_operations(rdp=clean_rdp)

    return {"rdp_id": rdp.pk}


def schedule_cancelled_rdp_set_rejection(
    *,
    rdp: Rdp,
    user_id: int,
    operation_ids: Iterable[UUID],
    clean_rdp_id: int | None = None,
) -> AsyncJob:
    """Schedule DedupEngine cleanup for a cancelled RDP."""
    config: dict[str, Any] = {
        "rdp_id": rdp.pk,
        "operation_ids": sorted(map(str, operation_ids)),
    }
    if clean_rdp_id is not None:
        config["clean_rdp_id"] = clean_rdp_id

    job = AsyncJob.objects.create(
        description="Reject cancelled RDP deduplication set",
        type=AsyncJob.JobType.TASK,
        owner_id=user_id,
        action=fqn(reject_cancelled_rdp_set_core),
        program_id=rdp.program_id,
        rdp=rdp,
        config=config,
    )
    transaction.on_commit(job.queue, robust=True)

    return job


def _approve_deduplication_sets(operation_ids: list[UUID]) -> None:
    """Approve the remote sets of operations after their RDP was pushed."""
    for operation_id in operation_ids:
        operation = get_rdp_operation(pk=operation_id)
        get_deduplication_backends()[operation.operation_type].approve(operation)


def schedule_deduplication_approval(rdp: Rdp) -> None:
    """Approve the remote sets of an RDP once the surrounding transaction commits."""
    if operation_ids := [operation.id for operation in deduplication_operations_for_rdp(rdp)]:
        # TODO(Vitali): Use Bitcaster to retry DedupEngine approval after a successful HOPE push.
        transaction.on_commit(partial(_approve_deduplication_sets, operation_ids), robust=True)
