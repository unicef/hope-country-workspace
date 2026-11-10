from django.db.models import Q, QuerySet

from country_workspace.models import Individual, Rdp, RdpOperation
from country_workspace.rdp.repository import qs_individuals_for_rdp

from .constants import BIOGRAPHIC_AFFECTING_FINDING_TYPES


def biographic_operation_for_rdp(*, rdp: Rdp) -> RdpOperation | None:
    """Return the biographic deduplication operation for an RDP."""
    return rdp.operations.filter(operation_type=RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION).first()


def qs_biographic_affected_individuals(*, operation: RdpOperation) -> QuerySet[Individual]:
    """Return RDP individuals affected by biographic findings."""
    return (
        qs_individuals_for_rdp(rdp=operation.rdp)
        .filter(
            Q(
                rdp_operation_findings__operation=operation,
                rdp_operation_findings__finding_type__in=BIOGRAPHIC_AFFECTING_FINDING_TYPES,
            )
            | Q(
                related_rdp_operation_findings__operation=operation,
                related_rdp_operation_findings__finding_type__in=BIOGRAPHIC_AFFECTING_FINDING_TYPES,
            )
        )
        .distinct()
    )
