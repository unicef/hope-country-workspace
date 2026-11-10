from collections.abc import Callable
from dataclasses import dataclass
from typing import NamedTuple

from country_workspace.models import RdpOperation
from country_workspace.rdp.policy import ActionCheck


class RejectionDecision(NamedTuple):
    """Whether cancelling an RDP is allowed and whether its remote set must be rejected."""

    check: ActionCheck
    required: bool = False


@dataclass(frozen=True, slots=True)
class DeduplicationBackend:
    """DedupEngine-specific behaviour of one deduplication operation type.

    Biometric and biographic deduplication are sibling implementations of this contract.
    Everything that talks to DedupEngine about the remote set of an operation sits behind it,
    so the generic RDP lifecycle (cancel, clean, push) only deals with operations.
    """

    operation_type: RdpOperation.Type
    # Pull the remote result of a running operation and complete or fail it.
    sync: Callable[[RdpOperation], bool]
    # Decide whether the remote set may be left behind or must be rejected when the RDP is cancelled.
    check_cancellation: Callable[[RdpOperation], RejectionDecision]
    # Verify that the remote set can back a clean replacement RDP.
    check_clean: Callable[[RdpOperation], ActionCheck]
    # Reject the remote set of a cancelled RDP. Idempotent; raises RdpWorkflowError when it is impossible.
    reject: Callable[[RdpOperation], None]
    # Approve the remote set after the RDP was pushed to HOPE.
    approve: Callable[[RdpOperation], None]
