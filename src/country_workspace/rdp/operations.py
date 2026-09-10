from uuid import UUID, uuid4

from django.db import transaction
from django.utils import timezone

from country_workspace.models import RdpOperation
from country_workspace.models.rdp_operation import RdpOperationStatus, RdpOperationType

from .policy import ActionCheck, RdpOperationPolicy
from .repository import lock_rdp_for_update, lock_rdp_operation_for_update


def claim_rdp_operation(*, rdp_id: int, operation_type: RdpOperationType) -> tuple[ActionCheck, RdpOperation | None]:
    """Claim an RDP operation for execution."""
    with transaction.atomic():
        rdp = lock_rdp_for_update(pk=rdp_id)

        try:
            operation = lock_rdp_operation_for_update(rdp=rdp, operation_type=operation_type)
        except RdpOperation.DoesNotExist:
            return ActionCheck(False, f"RDP: {operation_type.label} is not configured."), None

        check = RdpOperationPolicy(rdp, operation).start_check()
        if not check.allowed:
            return check, None

        operation.status = RdpOperationStatus.IN_PROGRESS
        operation.attempt_id = uuid4()
        operation.started_at = timezone.now()
        operation.completed_at = None
        operation.save(update_fields=["status", "attempt_id", "started_at", "completed_at"])

    return ActionCheck(True), operation


def finish_rdp_operation(
    *,
    rdp_id: int,
    operation_type: RdpOperationType,
    attempt_id: UUID,
    status: RdpOperationStatus,
) -> RdpOperation | None:
    """Finish the current RDP operation attempt."""
    if status not in {RdpOperationStatus.SUCCESS, RdpOperationStatus.FAILURE}:
        raise ValueError(f"Invalid final RDP operation status: {status}")

    with transaction.atomic():
        rdp = lock_rdp_for_update(pk=rdp_id)
        operation = lock_rdp_operation_for_update(rdp=rdp, operation_type=operation_type)

        if operation.status != RdpOperationStatus.IN_PROGRESS or operation.attempt_id != attempt_id:
            return None

        operation.status = status
        operation.completed_at = timezone.now()
        operation.save(update_fields=["status", "completed_at"])

    return operation
