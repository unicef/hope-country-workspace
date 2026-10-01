from django.db import transaction

from country_workspace.models import RdpOperation, RdpOperationFinding
from country_workspace.rdp.push.workflow import schedule_rdp_push_evaluation
from country_workspace.rdp.repository import lock_rdp_for_update

from .repository import fail_rdp_operation, finish_rdp_operation, has_incomplete_rdp_operations


def complete_rdp_operation(
    *,
    operation: RdpOperation,
    findings: list[RdpOperationFinding],
) -> bool:
    """Complete an RDP operation and schedule push evaluation when all operations finish."""
    try:
        with transaction.atomic():
            if not finish_rdp_operation(operation_id=operation.id, findings=findings):
                return False

            rdp = lock_rdp_for_update(pk=operation.rdp_id)
            if not has_incomplete_rdp_operations(rdp_id=rdp.pk):
                schedule_rdp_push_evaluation(rdp=rdp)
    except Exception as exc:
        fail_rdp_operation(operation_id=operation.id, error={"message": str(exc)})
        raise

    return True
