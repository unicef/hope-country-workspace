from typing import TYPE_CHECKING

from django.db.models import F, Q, QuerySet

from country_workspace.contrib.dedup_engine import FindingStatusCode
from country_workspace.models import Individual, Rdp, RdpOperation
from country_workspace.rdp.repository import qs_individuals_for_rdp, rdp_selection

from .constants import BIOMETRIC_AFFECTING_FINDING_TYPES, BIOMETRIC_IMAGE_ISSUE_FINDING_TYPES

if TYPE_CHECKING:
    from country_workspace.models import Program


def rdp_for_dedup(*, pk: int) -> Rdp:
    """Return RDP with related Program loaded for dedup workflow."""
    return Rdp.objects.select_related("program").get(pk=pk)


def biometric_operation_for_rdp(*, rdp: Rdp) -> RdpOperation | None:
    """Return the biometric deduplication operation for an RDP."""
    return rdp.operations.filter(
        operation_type=RdpOperation.Type.BIOMETRIC_DEDUPLICATION,
    ).first()


def qs_successful_biometric_operations() -> QuerySet[RdpOperation]:
    """Return successful biometric deduplication operations."""
    return RdpOperation.objects.filter(
        operation_type=RdpOperation.Type.BIOMETRIC_DEDUPLICATION,
        status=RdpOperation.Status.SUCCESS,
    )


def qs_biometric_duplicate_individuals(*, operation: RdpOperation) -> QuerySet[Individual]:
    """Return RDP individuals marked as biometric duplicates."""
    return (
        qs_individuals_for_rdp(rdp=operation.rdp)
        .filter(
            Q(
                rdp_operation_findings__operation=operation,
                rdp_operation_findings__finding_type=FindingStatusCode.DUPLICATE.name,
            )
            | Q(
                related_rdp_operation_findings__operation=operation,
                related_rdp_operation_findings__finding_type=FindingStatusCode.DUPLICATE.name,
            )
        )
        .distinct()
    )


def qs_biometric_affected_individuals(*, operation: RdpOperation) -> QuerySet[Individual]:
    """Return RDP individuals affected by biometric findings."""
    return (
        qs_individuals_for_rdp(rdp=operation.rdp)
        .filter(
            Q(
                rdp_operation_findings__operation=operation,
                rdp_operation_findings__finding_type__in=BIOMETRIC_AFFECTING_FINDING_TYPES,
            )
            | Q(
                related_rdp_operation_findings__operation=operation,
                related_rdp_operation_findings__finding_type__in=BIOMETRIC_AFFECTING_FINDING_TYPES,
            )
        )
        .distinct()
    )


def has_biometric_image_issues(*, operation: RdpOperation) -> bool:
    """Return whether biometric deduplication produced image-related issues."""
    return operation.findings.filter(
        finding_type__in=BIOMETRIC_IMAGE_ISSUE_FINDING_TYPES,
    ).exists()


def biometric_clean_rdp_selection(*, operation: RdpOperation) -> tuple[bool, list[int]]:
    """Return the RDP selection excluding beneficiaries affected by biometric findings."""
    master_detail, pks = rdp_selection(rdp=operation.rdp)
    affected = qs_biometric_affected_individuals(operation=operation)
    excluded = set(affected.values_list("household_id" if master_detail else "pk", flat=True))
    return master_detail, [pk for pk in pks if pk not in excluded]


def qs_successful_biometric_duplicate_individuals(*, program: "Program") -> QuerySet[Individual]:
    """Return individuals marked duplicate by successful biometric operations."""
    operations = qs_successful_biometric_operations().filter(rdp__program=program)
    direct = Q(
        rdp_operation_findings__operation__in=operations,
        rdp_operation_findings__finding_type=FindingStatusCode.DUPLICATE.name,
    )
    related = Q(
        related_rdp_operation_findings__operation__in=operations,
        related_rdp_operation_findings__finding_type=FindingStatusCode.DUPLICATE.name,
    )

    if program.is_master_detail:
        direct &= Q(rdp_operation_findings__operation__rdp__households__pk=F("household_id"))
        related &= Q(related_rdp_operation_findings__operation__rdp__households__pk=F("household_id"))
    else:
        direct &= Q(rdp_operation_findings__operation__rdp__individuals__pk=F("pk"))
        related &= Q(related_rdp_operation_findings__operation__rdp__individuals__pk=F("pk"))

    return Individual.objects.filter(direct | related).distinct()
