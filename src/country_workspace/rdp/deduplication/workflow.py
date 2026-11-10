from uuid import UUID

from country_workspace.models import RdpOperation
from country_workspace.rdp.operations.repository import get_rdp_operation

from .biometric.workflow import sync_biometric_result


def sync_deduplication_result(*, operation_id: UUID) -> bool:
    """Synchronize a DedupEngine-backed RDP operation."""
    try:
        operation = get_rdp_operation(pk=operation_id)
    except RdpOperation.DoesNotExist:
        return False

    if operation.operation_type == RdpOperation.Type.BIOMETRIC_DEDUPLICATION:
        return sync_biometric_result(operation)

    return False
