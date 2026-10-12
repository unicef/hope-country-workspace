from collections.abc import Iterable
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from country_workspace.models import Rdp, RdpOperation, RdpOperationFinding, RdpOperationUnit
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


def fail_rdp_operation(
    *,
    operation_id: UUID,
    error: dict[str, JSONValue],
    expected_attempt: int | None = None,
) -> bool:
    """Fail a running operation if it matches the expected attempt."""
    with transaction.atomic():
        operation = lock_rdp_operation_for_update(pk=operation_id)
        if operation.status != RdpOperation.Status.RUNNING:
            return False
        if expected_attempt is not None and operation.attempt != expected_attempt:
            return False

        operation.status = RdpOperation.Status.FAILURE
        operation.error = error
        operation.finished_at = timezone.now()
        operation.save(update_fields=["status", "error", "finished_at"])

    return True


def finish_rdp_operation(
    *,
    operation_id: UUID,
    findings: list[RdpOperationFinding] | None = None,
    expected_attempt: int | None = None,
) -> bool:
    """Finish a running operation, optionally replacing findings."""
    with transaction.atomic():
        operation = lock_rdp_operation_for_update(pk=operation_id)
        if operation.status != RdpOperation.Status.RUNNING:
            return False
        if expected_attempt is not None and operation.attempt != expected_attempt:
            return False

        if findings is not None:
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


def prepare_rdp_operation_units_for_retry(*, operation_id: UUID, expected_attempt: int) -> bool:
    """Prepare incomplete units only for the expected running attempt."""
    with transaction.atomic():
        if lock_current_rdp_operation(operation_id=operation_id, expected_attempt=expected_attempt) is None:
            return False
        RdpOperationUnit.objects.filter(operation_id=operation_id).exclude(
            status=RdpOperationUnit.Status.SUCCESS,
        ).update(status=RdpOperationUnit.Status.PENDING, error={})
    return True


def lock_current_rdp_operation(*, operation_id: UUID, expected_attempt: int) -> RdpOperation | None:
    """Lock an operation and return it only for its active running attempt."""
    operation = lock_rdp_operation_for_update(pk=operation_id)
    if (
        operation.status != RdpOperation.Status.RUNNING
        or operation.attempt != expected_attempt
        or operation.rdp.status != Rdp.PushStatus.PENDING
    ):
        return None
    return operation


def pending_rdp_operation_units(*, operation_id: UUID) -> QuerySet[RdpOperationUnit]:
    """Return pending operation units with their individuals."""
    return (
        RdpOperationUnit.objects.filter(operation_id=operation_id, status=RdpOperationUnit.Status.PENDING)
        .select_related("individual")
        .order_by("pk")
    )


def fail_rdp_operation_units(
    *,
    operation_id: UUID,
    expected_attempt: int,
    unit_ids: Iterable[int],
    error: dict[str, JSONValue],
) -> int:
    """Fail pending units only for the expected running operation attempt."""
    with transaction.atomic():
        if lock_current_rdp_operation(operation_id=operation_id, expected_attempt=expected_attempt) is None:
            return 0
        return RdpOperationUnit.objects.filter(
            operation_id=operation_id,
            pk__in=unit_ids,
            status=RdpOperationUnit.Status.PENDING,
        ).update(status=RdpOperationUnit.Status.FAILURE, error=error)


def has_rdp_operation_units(*, operation_id: UUID) -> bool:
    """Return whether an RDP operation has persistent units."""
    return RdpOperationUnit.objects.filter(operation_id=operation_id).exists()


def get_rdp_operation_units_outcome(*, operation_id: UUID) -> RdpOperation.Status | None:
    """Return a terminal outcome for nonempty operations without pending units."""
    units = RdpOperationUnit.objects.filter(operation_id=operation_id)
    if units.filter(status=RdpOperationUnit.Status.PENDING).exists():
        return None
    if units.filter(status=RdpOperationUnit.Status.FAILURE).exists():
        return RdpOperation.Status.FAILURE
    return RdpOperation.Status.SUCCESS if units.exists() else None


def record_rdp_operation_error(
    *,
    operation_id: UUID,
    expected_attempt: int,
    error: dict[str, JSONValue],
) -> bool:
    """Record an execution error, keeping attempts with pending units open."""
    with transaction.atomic():
        operation = lock_current_rdp_operation(operation_id=operation_id, expected_attempt=expected_attempt)
        if operation is None:
            return False

        has_pending = RdpOperationUnit.objects.filter(
            operation_id=operation_id, status=RdpOperationUnit.Status.PENDING
        ).exists()
        now = timezone.now()
        operation.error = error
        update_fields = ["error", "log"]
        if not has_pending:
            operation.status = RdpOperation.Status.FAILURE
            operation.finished_at = now
            update_fields += ["status", "finished_at"]

        entry: OperationLogEntry = {
            "timestamp": now.isoformat(),
            "action": "EXECUTION_ERROR",
            "result": {"attempt": expected_attempt, "error": error, "outcome": operation.status},
        }
        operation.log = [*(operation.log or []), entry]
        operation.save(update_fields=update_fields)
    return True
