from decimal import Decimal

from country_workspace.models import Rdp
from country_workspace.rdp.deduplication.types import ThresholdType
from country_workspace.rdp.operations.repository import has_incomplete_rdp_operations
from country_workspace.rdp.policy import ActionCheck, RdpActionPolicy


class PushPolicy(RdpActionPolicy):
    def review_push_check(self) -> ActionCheck:
        if self.rdp.status != Rdp.PushStatus.REVIEW_PENDING:
            return ActionCheck(False, f"RDP: can not push from review in status={self.rdp.status}")
        return ActionCheck(True)

    def retry_push_check(self) -> ActionCheck:
        if self.rdp.status != Rdp.PushStatus.FAILURE:
            return ActionCheck(False, f"RDP: can not retry push in status={self.rdp.status}")
        if has_incomplete_rdp_operations(rdp_id=self.rdp.pk):
            return ActionCheck(False, "RDP: all operations must complete successfully before retrying push.")
        return ActionCheck(True)


def get_push_policy(rdp: Rdp) -> PushPolicy:
    if (policy := getattr(rdp, "_push_policy", None)) is None:
        policy = PushPolicy(rdp)
        rdp._push_policy = policy
    return policy


def threshold_exceeded(
    *,
    findings_count: int,
    total_count: int,
    threshold_type: ThresholdType,
    threshold_value: Decimal,
) -> bool:
    """Check whether biometric findings exceed the selected threshold."""
    if findings_count < 0 or total_count <= 0 or threshold_value < 0:
        raise ValueError("Invalid deduplication threshold inputs.")

    if threshold_type == ThresholdType.COUNT:
        return Decimal(findings_count) > threshold_value

    if threshold_type == ThresholdType.RATE:
        return Decimal(findings_count) * 100 > threshold_value * total_count

    raise ValueError(f"Invalid threshold type: {threshold_type}")
