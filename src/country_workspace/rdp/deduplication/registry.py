from functools import cache

from country_workspace.models import RdpOperation

from .backend import DeduplicationBackend


@cache
def get_deduplication_backends() -> dict[str, DeduplicationBackend]:
    """Return the DedupEngine-backed operation implementations by operation type.

    Imported lazily: the backends depend on the operation workflow, which in turn depends on push.
    """
    from .biographic.backend import BIOGRAPHIC_BACKEND
    from .biometric.backend import BIOMETRIC_BACKEND

    return {backend.operation_type.value: backend for backend in (BIOMETRIC_BACKEND, BIOGRAPHIC_BACKEND)}


def get_deduplication_backend(operation: RdpOperation) -> DeduplicationBackend | None:
    """Return the DedupEngine implementation of an operation, or None for other operation types."""
    return get_deduplication_backends().get(operation.operation_type)
