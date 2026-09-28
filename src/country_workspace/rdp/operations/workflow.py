from uuid import UUID

from django.db import transaction
from strategy_field.utils import fqn

from country_workspace.models import AsyncJob, Rdp, RdpOperation
from country_workspace.rdp.repository import lock_rdp_for_update
from country_workspace.rdp.types import JSONValue

from .definitions import RDP_OPERATION_DEFINITIONS
from .repository import claim_rdp_operation, fail_rdp_operation, failed_rdp_operations


def run_rdp_operation_core(job: AsyncJob) -> dict[str, JSONValue]:
    """Run the RDP operation referenced by an async job."""
    operation_id = UUID(job.config["operation_id"])
    if (operation := claim_rdp_operation(operation_id)) is None:
        return {"operation_id": str(operation_id), "started": False}

    if (definition := RDP_OPERATION_DEFINITIONS.get(operation.operation_type)) is None:
        message = f"Unsupported RDP operation type: {operation.operation_type!r}"
        fail_rdp_operation(operation_id=operation.id, error={"message": message})
        raise ValueError(message)

    try:
        definition.runner(operation)
    except Exception as exc:
        fail_rdp_operation(operation_id=operation.id, error={"message": str(exc)})
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


def retry_failed_rdp_operations(*, rdp_id: int, owner_id: int) -> int:
    """Schedule failed operations of a pending RDP for retry."""
    with transaction.atomic():
        rdp = lock_rdp_for_update(pk=rdp_id)
        if rdp.status != Rdp.PushStatus.PENDING:
            return 0

        operations = list(failed_rdp_operations(rdp_id=rdp_id))
        for operation in operations:
            schedule_rdp_operation(operation=operation, owner_id=owner_id)

    return len(operations)
