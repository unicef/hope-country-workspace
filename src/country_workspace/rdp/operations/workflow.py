from uuid import UUID

from django.db import transaction
from django.db.models import Q, QuerySet
from strategy_field.utils import fqn

from country_workspace.models import AsyncJob, Rdp, RdpOperation
from country_workspace.rdp.repository import lock_rdp_for_update
from country_workspace.rdp.types import JSONValue

from .errors import handle_rdp_operation_error
from .repository import claim_rdp_operation, fail_rdp_operation


def run_rdp_operation_core(job: AsyncJob) -> dict[str, JSONValue]:
    """Run the RDP operation referenced by an async job."""
    operation_id = UUID(job.config["operation_id"])
    if (operation := claim_rdp_operation(operation_id)) is None:
        return {"operation_id": str(operation_id), "started": False}

    from .definitions import RDP_OPERATION_DEFINITIONS

    if (definition := RDP_OPERATION_DEFINITIONS.get(operation.operation_type)) is None:
        message = f"Unsupported RDP operation type: {operation.operation_type!r}"
        fail_rdp_operation(
            operation_id=operation.id,
            error={"message": message},
            expected_attempt=operation.attempt,
        )
        raise ValueError(message)

    try:
        definition.runner(operation)
    except Exception as exc:
        handle_rdp_operation_error(operation=operation, exc=exc)
        raise

    return {"operation_id": str(operation.id), "started": True}


def schedule_rdp_operation(*, operation: RdpOperation, owner_id: int) -> AsyncJob:
    """Create and queue an RDP operation job after commit."""
    job = AsyncJob.objects.create(
        description=f"Run RDP operation: {RdpOperation.Type(operation.operation_type).label}",
        type=AsyncJob.JobType.TASK,
        owner_id=owner_id,
        action=fqn(run_rdp_operation_core),
        program_id=operation.rdp.program_id,
        rdp_id=operation.rdp_id,
        config={"operation_id": str(operation.id)},
    )
    transaction.on_commit(job.queue, robust=True)
    return job


def schedule_rdp_operations(*, rdp: Rdp) -> None:
    """Schedule all configured RDP operations."""
    for operation in rdp.operations.all():
        schedule_rdp_operation(operation=operation, owner_id=rdp.pushed_by_id)


def _retryable_rdp_operations(*, rdp_id: int) -> QuerySet[RdpOperation]:
    """Return failed operations and running operations that support manual retry."""
    from .definitions import RDP_OPERATION_DEFINITIONS

    running_types = [
        operation_type
        for operation_type, definition in RDP_OPERATION_DEFINITIONS.items()
        if definition.can_retry_while_running
    ]
    return RdpOperation.objects.filter(rdp_id=rdp_id).filter(
        Q(status=RdpOperation.Status.FAILURE) | Q(status=RdpOperation.Status.RUNNING, operation_type__in=running_types)
    )


def has_retryable_rdp_operations(*, rdp_id: int) -> bool:
    """Return whether an RDP has operations available for manual retry."""
    return _retryable_rdp_operations(rdp_id=rdp_id).exists()


def retry_rdp_operations(*, rdp_id: int, owner_id: int) -> int | None:
    """Retry failed operations or recover retryable running operations."""
    with transaction.atomic():
        candidates = list(_retryable_rdp_operations(rdp_id=rdp_id).select_for_update().order_by("pk"))
        if not candidates:
            return 0

        rdp = lock_rdp_for_update(pk=rdp_id)
        if rdp.program.cleanup_in_progress:
            return None
        if rdp.status != Rdp.PushStatus.PENDING:
            return 0

        operations = [
            operation for operation in candidates if operation.status == RdpOperation.Status.FAILURE
        ] or candidates
        scheduled = 0

        for operation in operations:
            if operation.status == RdpOperation.Status.RUNNING and not fail_rdp_operation(
                operation_id=operation.id,
                expected_attempt=operation.attempt,
                error={"message": "Operation manually restarted while still running."},
            ):
                continue

            schedule_rdp_operation(operation=operation, owner_id=owner_id)
            scheduled += 1

    return scheduled
