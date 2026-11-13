from django.db.models import QuerySet

from country_workspace.models import Individual, Rdp, RdpOperation

from ..repository import operation_for_rdp, qs_affected_individuals
from .constants import BIOMETRIC_AFFECTING_FINDING_TYPES


def biometric_operation_for_rdp(*, rdp: Rdp) -> RdpOperation | None:
    """Return the biometric deduplication operation for an RDP."""
    return operation_for_rdp(rdp=rdp, operation_type=RdpOperation.Type.BIOMETRIC_DEDUPLICATION)


def qs_biometric_affected_individuals(*, operation: RdpOperation) -> QuerySet[Individual]:
    """Return RDP individuals affected by biometric findings."""
    return qs_affected_individuals(operation=operation, finding_types=BIOMETRIC_AFFECTING_FINDING_TYPES)
