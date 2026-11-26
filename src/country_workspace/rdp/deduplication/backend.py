from collections.abc import Callable
from dataclasses import dataclass
from typing import NamedTuple

from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import RdpOperation
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.policy import ActionCheck

from .actions import approve_remote_set_after_successful_push, reject_remote_set


class RejectionDecision(NamedTuple):
    """Whether cancelling an RDP is allowed and whether its remote set must be rejected."""

    check: ActionCheck
    required: bool = False


@dataclass(frozen=True, slots=True)
class DeduplicationBackend:
    """DedupEngine-specific behaviour of one deduplication operation type.

    Biometric and biographic deduplication are sibling implementations of this contract.
    The remote set of an operation is addressed by the operation id in both, so the generic RDP lifecycle
    (cancel, clean, push) only deals with operations. What differs between the types is declared here:
    how to reach DedupEngine and which remote states allow which step. The shared rules built on top of
    those declarations are the methods below.
    """

    operation_type: RdpOperation.Type
    # "biometric" or "biographic", used in messages.
    kind: str
    # What DedupEngine calls the remote set ("deduplication set", "biographic dataset"), used in messages.
    remote_label: str
    # Pull the remote result of a running operation and complete or fail it.
    sync: Callable[[RdpOperation], bool]
    # Return the remote state of the operation set, or None when DedupEngine does not know it.
    retrieve_state: Callable[[RdpOperation], str | None]
    # The remote calls. They raise RemoteError / RemoteUnavailableError; logging and policy are shared.
    approve_remote: Callable[[RdpOperation], None]
    reject_remote: Callable[[RdpOperation], None]
    # Scored and awaiting a decision: cancelling the RDP must reject the set.
    rejectable_states: frozenset[str]
    # The set holds nothing that blocks the program, so it may be left behind when the RDP is cancelled.
    non_blocking_states: frozenset[str]
    # The only state a clean replacement RDP can be built from.
    clean_state: str
    # States in which there is nothing left to reject (besides the set not existing).
    reject_ignored_states: frozenset[str]

    def check_cancellation(self, operation: RdpOperation) -> RejectionDecision:
        """Check whether the remote set must be rejected on cancellation."""
        state = self.retrieve_state(operation)

        if state in self.rejectable_states:
            return RejectionDecision(ActionCheck(True), required=True)
        if state is None or state in self.non_blocking_states:
            return RejectionDecision(ActionCheck(True))

        return RejectionDecision(
            ActionCheck(False, f"DedupEngine: can not cancel with {self.remote_label} in state={state!r}.")
        )

    def check_clean(self, operation: RdpOperation) -> ActionCheck:
        """Check that the remote set can back a clean replacement RDP."""
        if operation.status != RdpOperation.Status.SUCCESS:
            return ActionCheck(False, f"RDP: successful {self.kind} deduplication is required.")

        if (state := self.retrieve_state(operation)) != self.clean_state:
            return ActionCheck(
                False, f"DedupEngine: can not create clean RDP with {self.remote_label} in state={state!r}."
            )

        return ActionCheck(True)

    def reject(self, operation: RdpOperation) -> None:
        """Reject the remote set of a cancelled RDP, unless there is nothing left to reject.

        Idempotent. Raises RdpWorkflowError when the set is in a state that cannot be rejected.
        """
        try:
            state = self.retrieve_state(operation)
            if state in self.rejectable_states:
                reject_remote_set(operation, self.reject_remote)
            elif state is not None and state not in self.reject_ignored_states:
                raise RdpWorkflowError(
                    {"errors": [f"DedupEngine: can not reject {self.remote_label} in state={state!r}."]}
                )
        except (RemoteError, RemoteUnavailableError) as exc:
            raise RdpWorkflowError({"errors": [str(exc)]}) from exc

    def approve(self, operation: RdpOperation) -> None:
        """Approve the remote set after a successful HOPE push."""
        approve_remote_set_after_successful_push(operation, self.approve_remote)
