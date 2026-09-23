from functools import cached_property
from decimal import Decimal

from country_workspace.contrib.dedup_engine import PUSHABLE_DEDUPLICATION_SET_STATES
from country_workspace.models import Rdp
from country_workspace.rdp.deduplication.policy import DeduplicationPolicy, get_deduplication_policy
from country_workspace.rdp.deduplication.types import ThresholdType
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
        return self._deduplication_push_check()

    def review_push_check(self) -> ActionCheck:
        if self.rdp.status != Rdp.PushStatus.REVIEW_PENDING:
            return ActionCheck(False, f"RDP: can not push from review in status={self.rdp.status}")
        if self.rdp.is_dedup_settings_locked:
            return ActionCheck(False, "RDP: can not push while deduplication is queued or running.")
        return self._deduplication_push_check()

    def _deduplication_push_check(self) -> ActionCheck:
        if not self.deduplication_policy.is_biometric_deduplication_enabled:
            return ActionCheck(True)
        if not self.deduplication_policy.has_deduplication_set_id:
            return ActionCheck(False, "DedupEngine: deduplication_set_id is not set for this RDP.")
        if self.rdp.deduplication_findings_count is None:
            return ActionCheck(False, "RDP: completed deduplication result is required.")
        if (state := self.deduplication_policy.deduplication_set_state) in PUSHABLE_DEDUPLICATION_SET_STATES:
            return ActionCheck(True)
        return ActionCheck(False, f"DedupEngine: can not push with deduplication set in state={state!r}.")


def get_push_policy(rdp: Rdp) -> PushPolicy:
    if (policy := getattr(rdp, "_push_policy", None)) is None:
        policy = PushPolicy(rdp)
        rdp._push_policy = policy
    return policy


def threshold_exceeded(
    *,
    marked_count: int,
    total_count: int,
    threshold_type: ThresholdType,
    threshold_value: Decimal,
) -> bool:
    """Check whether marked individuals exceed the selected threshold."""
    if marked_count < 0 or total_count <= 0 or threshold_value < 0:
        raise ValueError("Invalid deduplication threshold inputs.")

    if threshold_type == ThresholdType.COUNT:
        return Decimal(marked_count) > threshold_value

    if threshold_type == ThresholdType.PERCENT:
        if threshold_value > 100:
            raise ValueError("Percentage threshold cannot exceed 100.")
        return Decimal(marked_count) * 100 > threshold_value * total_count

    raise ValueError(f"Invalid threshold type: {threshold_type}")
