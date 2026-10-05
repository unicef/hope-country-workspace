from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from country_workspace.models import Rdp, RdpOperation, RdpOperationFinding
from country_workspace.rdp.types import JSONValue, OperationLogResult
from country_workspace.rdp.repository import lock_rdp_for_update

if TYPE_CHECKING:
    from country_workspace.rdp.types import OperationLogEntry


def lock_rdp_operation_for_update(*, pk: UUID) -> RdpOperation:
    """Return RDP operation locked for update."""
    return RdpOperation.objects.select_for_update().select_related("rdp__program").get(pk=pk)


def get_rdp_operation(*, pk: UUID) -> RdpOperation:
    """Return an RDP operation with its RDP context."""
    return RdpOperation.objects.select_related("rdp__program__beneficiary_group").get(pk=pk)


def has_incomplete_rdp_operations(*, rdp_id: int) -> bool:
    """Return whether an RDP has operations that have not succeeded."""
    return RdpOperation.objects.filter(rdp_id=rdp_id).exclude(status=RdpOperation.Status.SUCCESS).exists()


def claim_rdp_operation(operation_id: UUID) -> RdpOperation | None:
    """Claim a pending or failed RDP operation for execution."""
    with transaction.atomic():
        operation = lock_rdp_operation_for_update(pk=operation_id)
        rdp = lock_rdp_for_update(pk=operation.rdp_id)

        if rdp.status != Rdp.PushStatus.PENDING or operation.status not in {
            RdpOperation.Status.PENDING,
            RdpOperation.Status.FAILURE,
        }:
            return None

        operation.status = RdpOperation.Status.RUNNING
        operation.attempt += 1
        operation.error = {}
        operation.started_at = timezone.now()
        operation.finished_at = None
        operation.save(update_fields=["status", "attempt", "error", "started_at", "finished_at"])

    return operation


def fail_rdp_operation(*, operation_id: UUID, error: dict[str, JSONValue]) -> bool:
    """Mark a running RDP operation as failed."""
    with transaction.atomic():
        operation = lock_rdp_operation_for_update(pk=operation_id)
        if operation.status != RdpOperation.Status.RUNNING:
            return False

        operation.status = RdpOperation.Status.FAILURE
        operation.error = error
        operation.finished_at = timezone.now()
        operation.save(update_fields=["status", "error", "finished_at"])

    return True


def finish_rdp_operation(*, operation_id: UUID, findings: list[RdpOperationFinding]) -> bool:
    """Replace findings and mark a running RDP operation as successful."""
    with transaction.atomic():
        operation = lock_rdp_operation_for_update(pk=operation_id)
        if operation.status != RdpOperation.Status.RUNNING:
            return False

        operation.findings.all().delete()
        for finding in findings:
            finding.operation = operation
        RdpOperationFinding.objects.bulk_create(findings)

        operation.status = RdpOperation.Status.SUCCESS
        operation.error = {}
        operation.finished_at = timezone.now()
        operation.save(update_fields=["status", "error", "finished_at"])

    return True


def failed_rdp_operations(*, rdp_id: int) -> QuerySet[RdpOperation]:
    """Return failed operations for an RDP."""
    return RdpOperation.objects.filter(
        rdp_id=rdp_id,
        status=RdpOperation.Status.FAILURE,
    )


def append_rdp_operation_log(
    *,
    operation_id: UUID,
    action: str,
    result: OperationLogResult | None = None,
) -> None:
    """Append a log entry to an RDP operation."""
    with transaction.atomic():
        operation = lock_rdp_operation_for_update(pk=operation_id)
        entry: OperationLogEntry = {
            "timestamp": timezone.now().isoformat(),
            "action": action,
        }
        if result is not None:
            entry["result"] = result

        operation.log = [*(operation.log or []), entry]
        operation.save(update_fields=["log"])
