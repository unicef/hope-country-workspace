from decimal import Decimal

from country_workspace.models import Rdp, RdpOperation
from country_workspace.rdp.deduplication.types import ThresholdType
from country_workspace.rdp.policy import ActionCheck, RdpActionPolicy


class PushPolicy(RdpActionPolicy):
    def is_push_visible(self) -> bool:
        return self.is_open

    def push_check(self) -> ActionCheck:
        if not self.is_open:
            return ActionCheck(False, f"RDP: can not push in status={self.rdp.status}")
        return self._operations_check()

    def review_push_check(self) -> ActionCheck:
        if self.rdp.status != Rdp.PushStatus.REVIEW_PENDING:
            return ActionCheck(False, f"RDP: can not push from review in status={self.rdp.status}")
        return self._operations_check()

    def _operations_check(self) -> ActionCheck:
        if self.rdp.operations.exclude(status=RdpOperation.Status.SUCCESS).exists():
            return ActionCheck(False, "RDP: all operations must complete successfully before push.")
        return ActionCheck(True)


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
