from collections.abc import Collection

from django.db.models import Q, QuerySet

from country_workspace.models import Individual, Rdp, RdpOperation
from country_workspace.rdp.repository import qs_individuals_for_rdp


def operation_for_rdp(*, rdp: Rdp, operation_type: RdpOperation.Type) -> RdpOperation | None:
    """Return the operation of the given type for an RDP."""
    return rdp.operations.filter(operation_type=operation_type).first()


def qs_affected_individuals(*, operation: RdpOperation, finding_types: Collection[str]) -> QuerySet[Individual]:
    """Return RDP individuals on either side of the operation findings of the given types."""
    return (
        qs_individuals_for_rdp(rdp=operation.rdp)
        .filter(
            Q(
                rdp_operation_findings__operation=operation,
                rdp_operation_findings__finding_type__in=finding_types,
            )
            | Q(
                related_rdp_operation_findings__operation=operation,
                related_rdp_operation_findings__finding_type__in=finding_types,
            )
        )
        .distinct()
    )
