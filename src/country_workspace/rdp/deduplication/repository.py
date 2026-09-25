from django.db.models import Q, QuerySet

from country_workspace.contrib.dedup_engine import FindingStatusCode
from country_workspace.models import Individual, Rdp, RdpOperation
from country_workspace.rdp.repository import qs_individuals_for_rdp


def rdp_for_dedup(*, pk: int) -> Rdp:
    """Return RDP with related Program loaded for dedup workflow."""
    return Rdp.objects.select_related("program").get(pk=pk)


def biometric_operation_for_rdp(*, rdp: Rdp) -> RdpOperation | None:
    """Return the biometric deduplication operation for an RDP."""
    return rdp.operations.filter(
        operation_type=RdpOperation.Type.BIOMETRIC_DEDUPLICATION,
    ).first()


def qs_biometric_duplicate_individuals(*, operation: RdpOperation) -> QuerySet[Individual]:
    """Return RDP individuals marked as biometric duplicates."""
    findings = operation.findings.filter(finding_type=FindingStatusCode.DUPLICATE.name)
    return (
        qs_individuals_for_rdp(rdp=operation.rdp)
        .filter(Q(pk__in=findings.values("individual_id")) | Q(pk__in=findings.values("related_individual_id")))
        .distinct()
    )
