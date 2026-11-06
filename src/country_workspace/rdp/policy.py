from dataclasses import dataclass

from django.db.models import Q

from country_workspace.models import Program, Rdp, RdpOperation
from country_workspace.models.rdp import NON_TERMINAL_RDP_STATUSES

from .exceptions import RdpWorkflowError


@dataclass(slots=True, frozen=True)
class ActionCheck:
    allowed: bool
    reason: str | None = None

    def require(self) -> None:
        if not self.allowed:
            raise RdpWorkflowError({"errors": [self.reason or "Action is not allowed."]})


def beneficiary_data_change_check(program: Program) -> ActionCheck:
    """Check whether beneficiary data can be changed for the Program."""
    if Rdp.objects.filter(program_id=program.pk, status__in=NON_TERMINAL_RDP_STATUSES).exists():
        return ActionCheck(
            False,
            "Beneficiary data cannot be changed while the Program has an unfinished RDP. Cancel the RDP first.",
        )
    return ActionCheck(True)


class RdpActionPolicy:
    def __init__(self, rdp: Rdp) -> None:
        self.rdp = rdp

    @property
    def is_open(self) -> bool:
        return self.rdp.status in {self.rdp.PushStatus.PENDING, self.rdp.PushStatus.FAILURE}

    def is_cancel_visible(self) -> bool:
        return self.is_open or self.rdp.status == Rdp.PushStatus.REVIEW_PENDING

    def cancel_check(self) -> ActionCheck:
        if not self.is_cancel_visible():
            return ActionCheck(False, f"RDP: can not cancel in status={self.rdp.status}")
        if self.rdp.operations.filter(status=RdpOperation.Status.RUNNING).exists():
            return ActionCheck(False, "RDP: can not cancel while operations are running.")
        return ActionCheck(True)

    def reset_check(self) -> ActionCheck:
        """Check whether this RDP can be reset."""
        if self.rdp.program.cleanup_in_progress:
            return ActionCheck(False, "Program cleanup is in progress.")
        if self.rdp.status != Rdp.PushStatus.SUCCESS:
            return ActionCheck(False, f"RDP: can not reset in status={self.rdp.status}")
        if not (check := beneficiary_data_change_check(self.rdp.program)).allowed:
            return check
        if Rdp.objects.filter(
            Q(push_date__gt=self.rdp.push_date) | Q(push_date=self.rdp.push_date, pk__gt=self.rdp.pk),
            program_id=self.rdp.program_id,
            status=Rdp.PushStatus.SUCCESS,
        ).exists():
            return ActionCheck(False, "RDP: only the latest successful RDP can be reset.")
        return ActionCheck(True)


def get_rdp_policy(rdp: Rdp) -> RdpActionPolicy:
    if (policy := getattr(rdp, "_rdp_policy", None)) is None:
        policy = RdpActionPolicy(rdp)
        rdp._rdp_policy = policy
    return policy
