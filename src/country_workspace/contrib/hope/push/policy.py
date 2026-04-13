from dataclasses import dataclass
from functools import cached_property
from typing import Any

from country_workspace.contrib.dedup_engine import (
    DeduplicationSetState,
    get_deduplication_status,
    make_dedup_client,
)
from country_workspace.contrib.dedup_engine.deduplication_status import (
    CLONEABLE_DEDUPLICATION_SET_STATES,
    DedupResponseStatus,
)
from country_workspace.contrib.hope.exceptions import HopePushError
from country_workspace.models import Rdp

from .repository import has_other_pending_rdp, selection_owner_for_rdp


@dataclass(slots=True, frozen=True)
class ActionCheck:
    enabled: bool
    reason: str | None = None

    def require(self) -> None:
        if not self.enabled:
            raise HopePushError({"errors": [self.reason or "Action is not allowed."]})


class RdpActionPolicy:
    def __init__(self, rdp: Rdp) -> None:
        self.rdp = rdp

    @property
    def owner(self) -> Rdp:
        return selection_owner_for_rdp(rdp=self.rdp)

    @staticmethod
    def deduplication_status(rdp: Rdp) -> Any | None:
        if not rdp.deduplication_set_id:
            return None
        return get_deduplication_status(
            rdp.program.unicef_id,
            str(rdp.deduplication_set_id),
        )

    @cached_property
    def can_create_deduplication_set(self) -> bool:
        with make_dedup_client(self.rdp.program.unicef_id) as client:
            return client.can_create_deduplication_set()

    @cached_property
    def deduplication_set_state(self) -> str | None:
        if not self.rdp.deduplication_set_id:
            return None
        with make_dedup_client(
            self.rdp.program.unicef_id,
            deduplication_set_id=str(self.rdp.deduplication_set_id),
        ) as client:
            payload = client.retrieve_deduplication_set()
        return payload.get("state")

    def visible_deduplicate(self) -> bool:
        return self.rdp.status == self.rdp.PushStatus.PENDING and self.rdp.program.biometric_deduplication_enabled

    def visible_reject_ds(self) -> bool:
        return (
            self.rdp.status == self.rdp.PushStatus.PENDING
            and self.rdp.program.biometric_deduplication_enabled
            and bool(self.rdp.deduplication_set_id)
        )

    def visible_clone(self) -> bool:
        return self.rdp.program.biometric_deduplication_enabled

    def visible_push(self) -> bool:
        return self.rdp.status == self.rdp.PushStatus.PENDING

    def can_deduplicate(self) -> ActionCheck:
        if self.rdp.status != self.rdp.PushStatus.PENDING:
            return ActionCheck(False, f"RDP: can not run dedup in status={self.rdp.status}")
        if not self.rdp.program.biometric_deduplication_enabled:
            return ActionCheck(False, "DedupEngine: biometric deduplication is not enabled for this program.")
        if self.rdp.deduplication_set_id:
            if self.deduplication_set_state == DeduplicationSetState.DEDUPLICATED:
                return ActionCheck(False, "DedupEngine: can not run dedup for a deduplicated set.")
            return ActionCheck(True)
        if not self.can_create_deduplication_set:
            return ActionCheck(False, "DedupEngine: can not create deduplication set for this program.")
        return ActionCheck(True)

    def can_reject_ds(self) -> ActionCheck:
        if self.rdp.status != self.rdp.PushStatus.PENDING:
            return ActionCheck(False, f"RDP: can not reject deduplication set in status={self.rdp.status}")
        if not self.rdp.program.biometric_deduplication_enabled:
            return ActionCheck(False, "DedupEngine: biometric deduplication is not enabled for this program.")
        if not self.rdp.deduplication_set_id:
            return ActionCheck(False, "DedupEngine: deduplication_set_id is not set for this RDP.")
        if self.deduplication_set_state != DeduplicationSetState.DEDUPLICATED:
            return ActionCheck(
                False,
                f"DedupEngine: can not reject deduplication set in state={self.deduplication_set_state!r}.",
            )
        return ActionCheck(True)

    def can_clone(self) -> ActionCheck:
        if not self.rdp.program.biometric_deduplication_enabled:
            return ActionCheck(False, "DedupEngine: biometric deduplication is not enabled for this program.")

        exclude_ids = (self.rdp.pk,) if self.rdp.status == self.rdp.PushStatus.PENDING else ()
        if has_other_pending_rdp(owner=self.owner, exclude_ids=exclude_ids):
            return ActionCheck(False, "RDP: can not clone while another RDP is pending")

        status = self.deduplication_status(self.owner)
        if status is None:
            return ActionCheck(False, "DedupEngine: deduplication_set_id is not set for this RDP.")
        if status.response_status != DedupResponseStatus.OK:
            return ActionCheck(False, "DedupEngine: can not retrieve deduplication set status.")
        if status.deduplication_set_status not in CLONEABLE_DEDUPLICATION_SET_STATES:
            return ActionCheck(
                False,
                f"DedupEngine: can not clone RDP for deduplication set in state={status.deduplication_set_status!r}.",
            )
        return ActionCheck(True)

    def can_push(self) -> ActionCheck:
        if self.rdp.status != self.rdp.PushStatus.PENDING:
            return ActionCheck(False, f"RDP: can not push in status={self.rdp.status}")
        if not self.rdp.program.biometric_deduplication_enabled or not self.rdp.deduplication_set_id:
            return ActionCheck(True)
        if self.can_create_deduplication_set or self.deduplication_set_state == DeduplicationSetState.DEDUPLICATED:
            return ActionCheck(True)
        return ActionCheck(
            False,
            f"DedupEngine: can not push with deduplication set in state={self.deduplication_set_state!r}.",
        )

    def dedup_engine_state(self) -> str:
        result = "-"

        if self.rdp.status == self.rdp.PushStatus.PENDING:
            status = self.deduplication_status(self.rdp)
            if status is None:
                result = "Ready to start" if self.can_create_deduplication_set else "Can't create deduplication set"
            elif status.response_status == DedupResponseStatus.STATUS_UNAVAILABLE:
                result = DedupResponseStatus.STATUS_UNAVAILABLE.value
            elif status.response_status != DedupResponseStatus.OK:
                result = "Remote error"
            elif status.deduplication_set_status is None:
                result = "Created / waiting for status"
            elif status.findings_count >= 0:
                result = f"{status.deduplication_set_status} / {status.findings_count} findings"
            else:
                result = status.deduplication_set_status

        return result


def get_rdp_policy(rdp: Rdp) -> RdpActionPolicy:
    if (policy := getattr(rdp, "_rdp_policy", None)) is None:
        policy = RdpActionPolicy(rdp)
        rdp._rdp_policy = policy
    return policy
