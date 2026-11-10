from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.db.models import Exists, F, OuterRef, Q, QuerySet, Subquery
from django.utils import timezone

from country_workspace.models import Individual, Program, Rdp, RdpOperation, RdpOperationFinding, RdpOperationUnit
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


def qs_rdp_operation_findings(
    *,
    operation: RdpOperation,
    individual_id: int | None = None,
    household_id: int | None = None,
) -> QuerySet[RdpOperationFinding]:
    """Return operation findings involving the selected Individual or Household."""
    findings = operation.findings.all()

    if individual_id is not None:
        findings = findings.filter(Q(individual_id=individual_id) | Q(related_individual_id=individual_id))

    if household_id is not None:
        findings = findings.filter(
            Q(individual__household_id=household_id) | Q(related_individual__household_id=household_id)
        )

    return findings


@dataclass(frozen=True, slots=True)
class RdpOperationFindingsSummary:
    operation: RdpOperation
    finding_ids: frozenset[int]

    @property
    def findings_count(self) -> int:
        return len(self.finding_ids)


def _successful_program_operations(*, program: Program) -> QuerySet[RdpOperation]:
    """Return successful operations from non-cancelled RDPs."""
    return RdpOperation.objects.filter(
        rdp__program=program,
        status=RdpOperation.Status.SUCCESS,
    ).exclude(rdp__status=Rdp.PushStatus.CANCELLED)


def _finding_ids_by_operation_individual(
    *,
    operations: QuerySet[RdpOperation],
    individual_ids: set[int],
) -> dict[tuple[UUID, int], set[int]]:
    """Return finding IDs grouped by operation and involved Individual."""
    result: defaultdict[tuple[UUID, int], set[int]] = defaultdict(set)
    findings = RdpOperationFinding.objects.filter(operation__in=operations).filter(
        Q(individual_id__in=individual_ids) | Q(related_individual_id__in=individual_ids)
    )

    for finding_id, operation_id, individual_id, related_individual_id in findings.values_list(
        "pk",
        "operation_id",
        "individual_id",
        "related_individual_id",
    ):
        if individual_id in individual_ids:
            result[operation_id, individual_id].add(finding_id)
        if related_individual_id in individual_ids:
            result[operation_id, related_individual_id].add(finding_id)

    return dict(result)


def _operation_scope_by_individual(
    *,
    operations: QuerySet[RdpOperation],
    program: Program,
    individual_ids: set[int],
) -> defaultdict[UUID, set[int]]:
    """Return Individuals in scope of each operation."""
    result: defaultdict[UUID, set[int]] = defaultdict(set)

    for operation_id, individual_id in RdpOperationUnit.objects.filter(
        operation__in=operations,
        individual_id__in=individual_ids,
    ).values_list("operation_id", "individual_id"):
        result[operation_id].add(individual_id)

    biometric_membership = "rdp__households__members__pk" if program.is_master_detail else "rdp__individuals__pk"
    for operation_id, individual_id in operations.filter(
        operation_type=RdpOperation.Type.BIOMETRIC_DEDUPLICATION,
        **{f"{biometric_membership}__in": individual_ids},
    ).values_list("pk", biometric_membership):
        result[operation_id].add(individual_id)

    return result


def latest_operation_findings_by_individual(
    *,
    program: Program,
    individual_ids: Iterable[int],
) -> dict[int, list[RdpOperationFindingsSummary]]:
    """Return findings from each individual's latest relevant operation of each type."""
    individual_ids = set(individual_ids)
    if not individual_ids:
        return {}

    operations = _successful_program_operations(program=program)
    finding_ids = _finding_ids_by_operation_individual(
        operations=operations,
        individual_ids=individual_ids,
    )
    relevant = _operation_scope_by_individual(
        operations=operations,
        program=program,
        individual_ids=individual_ids,
    )
    for operation_id, individual_id in finding_ids:
        relevant[operation_id].add(individual_id)

    latest: dict[tuple[int, str], RdpOperation] = {}
    for operation in (
        operations.filter(pk__in=relevant.keys())
        .select_related("rdp")
        .order_by(
            "rdp__push_date",
            "rdp_id",
        )
    ):
        for individual_id in relevant[operation.pk]:
            latest[individual_id, operation.operation_type] = operation

    result: defaultdict[int, list[RdpOperationFindingsSummary]] = defaultdict(list)
    for (individual_id, __), operation in latest.items():
        if ids := finding_ids.get((operation.pk, individual_id)):
            result[individual_id].append(RdpOperationFindingsSummary(operation, frozenset(ids)))

    return {
        individual_id: sorted(summaries, key=lambda summary: summary.operation.operation_type)
        for individual_id, summaries in result.items()
    }


def qs_individuals_with_rdp_findings(*, rdp: Rdp) -> QuerySet[Individual]:
    """Return Individuals involved in findings of the selected RDP."""
    findings = RdpOperationFinding.objects.filter(operation__rdp=rdp).filter(
        Q(individual_id=OuterRef("pk")) | Q(related_individual_id=OuterRef("pk"))
    )
    return Individual.objects.filter(batch__program_id=rdp.program_id).filter(Exists(findings))


def _latest_relevant_operation_id(*, program: Program, operation_type: RdpOperation.Type) -> Subquery:
    """Return the latest relevant operation of one type for the outer Individual."""
    individual_id = OuterRef(OuterRef("pk"))
    operations = (
        _successful_program_operations(program=program)
        .filter(operation_type=operation_type)
        .alias(
            _has_unit=Exists(
                RdpOperationUnit.objects.filter(
                    operation_id=OuterRef("pk"),
                    individual_id=individual_id,
                )
            ),
            _has_finding=Exists(
                RdpOperationFinding.objects.filter(operation_id=OuterRef("pk")).filter(
                    Q(individual_id=individual_id) | Q(related_individual_id=individual_id)
                )
            ),
        )
    )

    relevant = Q(_has_unit=True) | Q(_has_finding=True)
    if operation_type == RdpOperation.Type.BIOMETRIC_DEDUPLICATION:
        membership = "rdp__households__members__pk" if program.is_master_detail else "rdp__individuals__pk"
        relevant |= Q(**{membership: OuterRef("pk")})

    return Subquery(operations.filter(relevant).order_by("-rdp__push_date", "-rdp_id").values("pk")[:1])


def _latest_finding_operation_id(*, program: Program, operation_type: RdpOperation.Type) -> Subquery:
    """Return the latest operation of one type with a finding involving the outer Individual."""
    return Subquery(
        _successful_program_operations(program=program)
        .filter(
            Q(findings__individual_id=OuterRef("pk")) | Q(findings__related_individual_id=OuterRef("pk")),
            operation_type=operation_type,
        )
        .order_by("-rdp__push_date", "-rdp_id")
        .values("pk")[:1]
    )


def qs_individuals_with_latest_operation_findings(*, program: Program) -> QuerySet:
    """Return Individuals with findings from at least one latest relevant operation."""
    individuals = Individual.objects.filter(batch__program=program)
    with_findings = Q(pk__isnull=True)

    for operation_type in RdpOperation.Type:
        suffix = operation_type.value.lower()
        latest_alias = f"_latest_{suffix}_operation_id"
        finding_alias = f"_latest_{suffix}_finding_operation_id"

        individuals = individuals.alias(
            **{
                latest_alias: _latest_relevant_operation_id(program=program, operation_type=operation_type),
                finding_alias: _latest_finding_operation_id(program=program, operation_type=operation_type),
            }
        )
        with_findings |= Q(**{latest_alias: F(finding_alias)})

    return individuals.filter(with_findings)


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
