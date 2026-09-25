from dataclasses import dataclass

from django.db.models import Q

from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import Rdp, RdpOperation

from .exceptions import RdpWorkflowError
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(slots=True, frozen=True)
class ActionCheck:
    allowed: bool
    reason: str | None = None

    def require(self) -> None:
        if not self.allowed:
            raise RdpWorkflowError({"errors": [self.reason or "Action is not allowed."]})


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
        if self.rdp.operations.filter(
            status__in={RdpOperation.Status.PENDING, RdpOperation.Status.RUNNING},
        ).exists():
            return ActionCheck(False, "RDP: can not cancel while operations are pending or running.")
        return ActionCheck(True)

    def reset_check(self) -> ActionCheck:
        """Check whether this RDP can be reset."""
        if self.rdp.status != Rdp.PushStatus.SUCCESS:
            return ActionCheck(False, f"RDP: can not reset in status={self.rdp.status}")
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


def require_policy_check(check: Callable[[], ActionCheck]) -> None:
    try:
        check().require()
    except (RemoteError, RemoteUnavailableError) as exc:
        raise RdpWorkflowError({"errors": [str(exc)]}) from exc
