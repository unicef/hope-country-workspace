from django.db import transaction

from country_workspace.models import RdpOperation, RdpOperationFinding
from country_workspace.rdp.push.workflow import schedule_rdp_push_evaluation

from .repository import fail_rdp_operation, finish_rdp_operation


def complete_rdp_operation(
    *,
    operation: RdpOperation,
    findings: list[RdpOperationFinding],
) -> bool:
    """Complete an RDP operation and schedule push evaluation."""
    try:
        with transaction.atomic():
            if not finish_rdp_operation(operation_id=operation.id, findings=findings):
                return False
            schedule_rdp_push_evaluation(rdp=operation.rdp)
    except Exception as exc:
        fail_rdp_operation(operation_id=operation.id, error={"message": str(exc)})
        raise

    return True
