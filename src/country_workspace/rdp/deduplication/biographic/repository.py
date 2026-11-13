from django.db.models import QuerySet

from country_workspace.models import Individual, Rdp, RdpOperation

from ..repository import operation_for_rdp, qs_affected_individuals
from .constants import BIOGRAPHIC_AFFECTING_FINDING_TYPES


def biographic_operation_for_rdp(*, rdp: Rdp) -> RdpOperation | None:
    """Return the biographic deduplication operation for an RDP."""
    return operation_for_rdp(rdp=rdp, operation_type=RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION)


def qs_biographic_affected_individuals(*, operation: RdpOperation) -> QuerySet[Individual]:
    """Return RDP individuals affected by biographic findings."""
    return qs_affected_individuals(operation=operation, finding_types=BIOGRAPHIC_AFFECTING_FINDING_TYPES)
