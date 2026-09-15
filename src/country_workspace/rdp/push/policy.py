from functools import cached_property

from country_workspace.contrib.dedup_engine import PUSHABLE_DEDUPLICATION_SET_STATES
from country_workspace.models import Rdp
from country_workspace.rdp.deduplication.policy import DeduplicationPolicy, get_deduplication_policy
from country_workspace.rdp.policy import ActionCheck, RdpActionPolicy


class PushPolicy(RdpActionPolicy):
    @cached_property
    def deduplication_policy(self) -> DeduplicationPolicy:
        return get_deduplication_policy(self.rdp)

    def is_push_visible(self) -> bool:
        return self.is_open

    def start_push_check(self) -> ActionCheck:
        if self.rdp.status == Rdp.PushStatus.PUSH_PENDING:
            return ActionCheck(False, "RDP: push to HOPE is already queued or running.")
        if self.rdp.is_dedup_settings_locked:
            return ActionCheck(False, "RDP: can not push while deduplication is queued or running.")
        return self.push_check()

    def push_check(self) -> ActionCheck:
        if not self.is_open:
            return ActionCheck(False, f"RDP: can not push in status={self.rdp.status}")
        if not self.deduplication_policy.is_biometric_deduplication_enabled:
            return ActionCheck(True)
        if not self.deduplication_policy.has_deduplication_set_id:
            return ActionCheck(False, "DedupEngine: deduplication_set_id is not set for this RDP.")
        if (state := self.deduplication_policy.deduplication_set_state) in PUSHABLE_DEDUPLICATION_SET_STATES:
            return ActionCheck(True)
        return ActionCheck(False, f"DedupEngine: can not push with deduplication set in state={state!r}.")


def get_push_policy(rdp: Rdp) -> PushPolicy:
    if (policy := getattr(rdp, "_push_policy", None)) is None:
        policy = PushPolicy(rdp)
        rdp._push_policy = policy
    return policy
