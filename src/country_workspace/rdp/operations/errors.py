import logging

from country_workspace.models import RdpOperation

from .repository import record_rdp_operation_error

logger = logging.getLogger(__name__)


def handle_rdp_operation_error(*, operation: RdpOperation, exc: Exception) -> None:
    """Record an execution error without masking it if persistence fails."""
    try:
        record_rdp_operation_error(
            operation_id=operation.id,
            expected_attempt=operation.attempt,
            error={"message": str(exc)},
        )
    except Exception:
        logger.exception(
            "Could not record RDP operation error operation=%s attempt=%s", operation.id, operation.attempt
        )
