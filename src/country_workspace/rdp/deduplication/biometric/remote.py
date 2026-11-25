from collections.abc import Generator
from contextlib import contextmanager

from country_workspace.contrib.dedup_engine import (
    BiometricClient,
    DeduplicationSetState,
    make_biometric_client,
    retrieve_deduplication_set_state,
)
from country_workspace.models import RdpOperation


@contextmanager
def make_operation_client(operation: RdpOperation) -> Generator[BiometricClient, None, None]:
    """Open a DedupEngine client bound to the set of an operation, which has the id of the operation."""
    with make_biometric_client(
        operation.rdp.program.unicef_id,
        deduplication_set_id=str(operation.id),
    ) as client:
        yield client


def retrieve_operation_state(operation: RdpOperation) -> DeduplicationSetState | None:
    """Return the DedupEngine state of the operation set, or None when it does not exist."""
    return retrieve_deduplication_set_state(
        group_reference_id=operation.rdp.program.unicef_id,
        deduplication_set_id=str(operation.id),
    )


def approve_operation_set(operation: RdpOperation) -> None:
    """Approve the DedupEngine set of an operation."""
    with make_operation_client(operation) as client:
        client.approve()


def reject_operation_set(operation: RdpOperation) -> None:
    """Reject the DedupEngine set of an operation."""
    with make_operation_client(operation) as client:
        client.reject()
