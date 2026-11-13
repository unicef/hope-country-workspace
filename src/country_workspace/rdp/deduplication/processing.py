from collections.abc import Callable
from typing import Any, NamedTuple

from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import RdpOperation, RdpOperationFinding
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.operations.completion import complete_rdp_operation
from country_workspace.rdp.operations.repository import fail_rdp_operation
from country_workspace.rdp.types import JSONValue

from .callbacks import build_dedup_operation_callback_url


class RemoteFailure(NamedTuple):
    """The remote set finished unsuccessfully; `error` is stored on the operation."""

    error: dict[str, JSONValue]


# What a type-specific fetch returns: nothing while the remote set is still working, a failure,
# or the findings that complete the operation.
type FetchOutcome = list[RdpOperationFinding] | RemoteFailure | None


def sync_remote_result(
    operation: RdpOperation,
    *,
    operation_type: RdpOperation.Type,
    fetch: Callable[[RdpOperation], FetchOutcome],
) -> bool:
    """Synchronize a running DedupEngine-backed operation with its remote set.

    Everything shared lives here: only a running operation of the right type is synchronized, an unreachable or
    malformed remote fails the operation, and the outcome completes or fails it for the attempt that was read.
    How to read the remote set and turn it into findings is up to `fetch`.
    """
    if operation.operation_type != operation_type or operation.status != RdpOperation.Status.RUNNING:
        return False

    try:
        outcome = fetch(operation)
    except (RemoteError, RemoteUnavailableError) as exc:
        return fail_rdp_operation(
            operation_id=operation.id,
            error={"message": str(exc)},
            expected_attempt=operation.attempt,
        )

    if outcome is None:
        return False
    if isinstance(outcome, RemoteFailure):
        return fail_rdp_operation(
            operation_id=operation.id,
            error=outcome.error,
            expected_attempt=operation.attempt,
        )
    return complete_rdp_operation(operation=operation, findings=outcome)


def get_or_create_remote_set[Payload](  # noqa: PLR0913
    operation: RdpOperation,
    *,
    label: str,
    retrieve: Callable[[], Payload | None],
    create: Callable[[str], Payload],
    remote_id: Callable[[Payload], object],
    has_input: Callable[[], bool],
    no_input_error: dict[str, Any],
    before_create: Callable[[], None] | None = None,
) -> Payload:
    """Return the remote set of an operation, creating it when DedupEngine does not know it yet.

    The remote set always has the id of the operation, so a retry or a recovery finds the set the previous attempt
    created instead of making another one. The set is only created when there is something to send, and the id
    DedupEngine reports must be the one that was asked for.
    """
    if (payload := retrieve()) is not None:
        return payload

    if not has_input():
        raise RdpWorkflowError(no_input_error)
    if before_create is not None:
        before_create()

    payload = create(build_dedup_operation_callback_url(operation_id=operation.id))
    if (created_id := remote_id(payload)) != str(operation.id):
        raise RemoteError(f"DedupEngine: {label} id mismatch: expected={operation.id}, got={created_id!r}")
    return payload
