from typing import Final

from country_workspace.models import Program
from country_workspace.models.rdp_operation import RdpOperationType


HOPE_MANAGED_RDP_OPERATIONS: Final[tuple[RdpOperationType, ...]] = (RdpOperationType.DEDUPLICATION,)

WORKSPACE_RDP_OPERATION_CHOICES = tuple(
    (operation.value, operation.label) for operation in RdpOperationType if operation not in HOPE_MANAGED_RDP_OPERATIONS
)


def get_hope_required_rdp_operations(program: Program) -> tuple[RdpOperationType, ...]:
    """Return RDP operations currently required by HOPE."""
    return (RdpOperationType.DEDUPLICATION,) if program.biometric_deduplication_enabled else ()


def get_effective_rdp_operations(program: Program) -> tuple[RdpOperationType, ...]:
    """Return all operations required for a newly created RDP."""
    managed = set(HOPE_MANAGED_RDP_OPERATIONS)
    required = set(get_hope_required_rdp_operations(program))
    configured = {
        operation for value in program.rdp_operations if (operation := RdpOperationType(value)) not in managed
    }
    return tuple(operation for operation in RdpOperationType if operation in required or operation in configured)
