from typing import Any

from django.db.models import BooleanField, Count, Exists, IntegerField, OuterRef, Q, QuerySet, Value

from country_workspace.models import Household, Individual, Program, Rdp, RdpOperation, RdpOperationFinding
from country_workspace.rdp.repository import qs_individuals_for_rdp

from .constants import BIOGRAPHIC_DUPLICATE_FINDING_TYPE


def biographic_operation_for_rdp(*, rdp: Rdp) -> RdpOperation | None:
    """Return the biographic deduplication operation for an RDP."""
    return rdp.operations.filter(operation_type=RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION).first()


def qs_successful_biographic_operations() -> QuerySet[RdpOperation]:
    """Return successful biographic deduplication operations."""
    return RdpOperation.objects.filter(
        operation_type=RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION,
        status=RdpOperation.Status.SUCCESS,
    )


def qs_biographic_duplicate_individuals(*, operation: RdpOperation) -> QuerySet[Individual]:
    """Return local individuals marked duplicate by a biographic operation."""
    return Individual.objects.filter(
        Q(
            rdp_operation_findings__operation=operation,
            rdp_operation_findings__finding_type=BIOGRAPHIC_DUPLICATE_FINDING_TYPE,
        )
        | Q(
            related_rdp_operation_findings__operation=operation,
            related_rdp_operation_findings__finding_type=BIOGRAPHIC_DUPLICATE_FINDING_TYPE,
        )
    ).distinct()


def qs_biographic_affected_individuals(*, operation: RdpOperation) -> QuerySet[Individual]:
    """Return the RDP individuals that have a biographic duplicate."""
    return (
        qs_individuals_for_rdp(rdp=operation.rdp)
        .filter(
            Q(
                rdp_operation_findings__operation=operation,
                rdp_operation_findings__finding_type=BIOGRAPHIC_DUPLICATE_FINDING_TYPE,
            )
            | Q(
                related_rdp_operation_findings__operation=operation,
                related_rdp_operation_findings__finding_type=BIOGRAPHIC_DUPLICATE_FINDING_TYPE,
            )
        )
        .distinct()
    )


def biographic_findings_count(*, operation: RdpOperation) -> int:
    """Return the number of RDP individuals with a biographic duplicate.

    DedupEngine reports a match from both sides when two people of the same RDP match each
    other, so the threshold counts individuals rather than findings, as HOPE does.
    """
    return qs_biographic_affected_individuals(operation=operation).count()


def _qs_successful_biographic_duplicate_individuals(*, program: Program) -> QuerySet[Individual]:
    """Return individuals marked duplicate by successful biographic operations of the program."""
    operations = qs_successful_biographic_operations().filter(rdp__program=program)
    return Individual.objects.filter(
        Q(
            rdp_operation_findings__operation__in=operations,
            rdp_operation_findings__finding_type=BIOGRAPHIC_DUPLICATE_FINDING_TYPE,
        )
        | Q(
            related_rdp_operation_findings__operation__in=operations,
            related_rdp_operation_findings__finding_type=BIOGRAPHIC_DUPLICATE_FINDING_TYPE,
        )
    ).distinct()


def biographic_findings_for_individual(
    *,
    individual: Individual,
    rdp: Rdp | None = None,
) -> list[dict[str, Any]]:
    """Return the biographic duplicates of an individual with the RDP they were found in.

    Each entry describes the counterpart: its id, the RDP of the operation, and the best score,
    scope and name DedupEngine reported for the pair.
    """
    operations = qs_successful_biographic_operations().filter(rdp__program=individual.program)
    if rdp:
        operations = operations.filter(rdp=rdp)

    matches: dict[int, dict[str, Any]] = {}
    findings = (
        RdpOperationFinding.objects.filter(
            Q(individual=individual) | Q(related_individual=individual),
            operation__in=operations,
            finding_type=BIOGRAPHIC_DUPLICATE_FINDING_TYPE,
        )
        .order_by("operation__rdp__push_date", "operation__rdp_id", "pk")
        .values_list("individual_id", "related_individual_id", "operation__rdp_id", "details")
    )
    for first_id, second_id, finding_rdp_id, details in findings:
        counterpart_id = second_id if first_id == individual.pk else first_id
        if counterpart_id is None:
            continue
        info = details or {}
        match = {
            "pk": counterpart_id,
            "rdp_id": finding_rdp_id,
            "score": info.get("score"),
            "scope": info.get("scope"),
            "full_name": info.get("matched_full_name"),
        }
        known = matches.get(counterpart_id)
        if known is None or (match["score"] or 0) > (known["score"] or 0):
            matches[counterpart_id] = match

    return [matches[pk] for pk in sorted(matches)]


def annotate_biographic_households(
    qs: QuerySet[Household],
    *,
    program: Program,
    rdp: Rdp | None,
) -> QuerySet[Household]:
    """Annotate households with biographic result counts."""
    if rdp:
        operation = biographic_operation_for_rdp(rdp=rdp)
        duplicates = (
            qs_biographic_duplicate_individuals(operation=operation) if operation else Individual.objects.none()
        )
        actual_members = Q()
        result_available = Value(
            operation is not None and operation.status == RdpOperation.Status.SUCCESS,
            output_field=BooleanField(),
        )
    else:
        duplicates = _qs_successful_biographic_duplicate_individuals(program=program)
        actual_members = Q(members__removed=False)
        result_available = Exists(
            qs_successful_biographic_operations().filter(
                rdp__program=program,
                rdp__households__pk=OuterRef("pk"),
            )
        ) | Exists(
            duplicates.filter(
                household_id=OuterRef("pk"),
                removed=False,
            )
        )

    return qs.annotate(
        _biographic_member_count=Count("members", filter=actual_members, distinct=True),
        _biographic_duplicate_member_count=Count(
            "members", filter=actual_members & Q(members__in=duplicates), distinct=True
        ),
        _biographic_result_available=result_available,
        _biographic_selected_rdp_id=Value(rdp.pk if rdp else None, output_field=IntegerField()),
    )


def annotate_biographic_individuals(
    qs: QuerySet[Individual],
    *,
    program: Program,
    rdp: Rdp | None,
) -> QuerySet[Individual]:
    """Annotate individuals with biographic result state."""
    if rdp:
        operation = biographic_operation_for_rdp(rdp=rdp)
        duplicates = (
            qs_biographic_duplicate_individuals(operation=operation) if operation else Individual.objects.none()
        )
        biographic_result_available = Value(
            operation is not None and operation.status == RdpOperation.Status.SUCCESS,
            output_field=BooleanField(),
        )
    else:
        duplicates = _qs_successful_biographic_duplicate_individuals(program=program)
        operations = qs_successful_biographic_operations().filter(rdp__program=program)
        membership = (
            Q(rdp__households__pk=OuterRef("household_id"))
            if program.is_master_detail
            else Q(rdp__individuals__pk=OuterRef("pk"))
        )
        biographic_result_available = Exists(operations.filter(membership)) | Exists(
            duplicates.filter(pk=OuterRef("pk"))
        )

    return qs.annotate(
        _is_biographic_duplicate=Exists(duplicates.filter(pk=OuterRef("pk"))),
        _biographic_result_available=biographic_result_available,
    )
