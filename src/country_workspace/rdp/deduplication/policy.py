from functools import cached_property

from country_workspace.contrib.dedup_engine import (
    PROCESSABLE_DEDUPLICATION_SET_STATES,
    DedupClientStatus,
    get_deduplication_status,
    make_dedup_client,
)
from country_workspace.models import Rdp, RdpOperation
from country_workspace.rdp.policy.common import ActionCheck
from country_workspace.rdp.policy.operation import RdpOperationPolicy


class DeduplicationPolicy:
    def __init__(self, rdp: Rdp, operation: RdpOperation) -> None:
        self.rdp = rdp
        self.operation = operation

    @property
    def group_reference_id(self) -> str:
        return self.rdp.program.unicef_id

    @property
    def deduplication_set_id(self) -> str | None:
        return self.operation.external_id

    @cached_property
    def can_create_deduplication_set(self) -> bool:
        with make_dedup_client(self.group_reference_id) as client:
            return client.can_create_deduplication_set()

    @cached_property
    def deduplication_set_state(self) -> str | None:
        if not (deduplication_set_id := self.deduplication_set_id):
            return None
        with make_dedup_client(
            self.group_reference_id,
            deduplication_set_id=deduplication_set_id,
        ) as client:
            return client.retrieve_deduplication_set().get("state")

    def deduplication_status(self) -> DedupClientStatus | None:
        """Return the current DedupEngine status for this operation."""
        if not (deduplication_set_id := self.deduplication_set_id):
            return None
        return get_deduplication_status(
            group_reference_id=self.group_reference_id,
            deduplication_set_id=deduplication_set_id,
        )

    def start_check(self) -> ActionCheck:
        """Check whether deduplication can be started."""
        if self.operation.type != RdpOperation.Type.DEDUPLICATION:
            return ActionCheck(False, "RDP: operation is not deduplication.")

        if not (check := RdpOperationPolicy(self.rdp, self.operation).start_check()).allowed:
            return check

        if self.can_create_deduplication_set:
            return ActionCheck(True)

        if not self.deduplication_set_id:
            return ActionCheck(False, "DedupEngine: can not create deduplication set for this program.")

        if self.deduplication_set_state in PROCESSABLE_DEDUPLICATION_SET_STATES:
            return ActionCheck(True)

        return ActionCheck(
            False,
            f"DedupEngine: can not process deduplication set in state={self.deduplication_set_state!r}.",
        )
