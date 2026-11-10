from django.db import transaction

from country_workspace.models import RdpOperation, RdpOperationFinding
from country_workspace.rdp.push.workflow import schedule_rdp_push_evaluation
from country_workspace.rdp.repository import lock_rdp_for_update

from .errors import handle_rdp_operation_error
from .repository import (
    fail_rdp_operation,
    finish_rdp_operation,
    get_rdp_operation_units_outcome,
    has_incomplete_rdp_operations,
    lock_current_rdp_operation,
)


def complete_rdp_operation(
    *,
    operation: RdpOperation,
    findings: list[RdpOperationFinding] | None = None,
) -> bool:
    """Complete an operation and schedule push evaluation when all operations succeed."""
    try:
        with transaction.atomic():
            if not finish_rdp_operation(
                operation_id=operation.id,
                findings=findings,
                expected_attempt=operation.attempt,
            ):
                return False

            rdp = lock_rdp_for_update(pk=operation.rdp_id)
            if not rdp.program.cleanup_in_progress and not has_incomplete_rdp_operations(rdp_id=rdp.pk):
                schedule_rdp_push_evaluation(rdp=rdp)
    except Exception as exc:
        handle_rdp_operation_error(operation=operation, exc=exc)
        raise

    return True


def finalize_rdp_operation_from_units(*, operation: RdpOperation) -> bool:
    """Finalize a current operation when all its persistent units are terminal."""
    with transaction.atomic():
        current_operation = lock_current_rdp_operation(operation_id=operation.id, expected_attempt=operation.attempt)
        if current_operation is None:
            return False

        outcome = get_rdp_operation_units_outcome(operation_id=operation.id)
        if outcome == RdpOperation.Status.FAILURE:
            return fail_rdp_operation(
                operation_id=operation.id,
                expected_attempt=operation.attempt,
                error={"message": "Some operation units failed."},
            )
        if outcome == RdpOperation.Status.SUCCESS:
            return complete_rdp_operation(operation=current_operation)
        return False
