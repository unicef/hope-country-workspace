from country_workspace.models import Rdp, RdpOperation

from .common import ActionCheck


class RdpOperationPolicy:
    def __init__(self, rdp: Rdp, operation: RdpOperation) -> None:
        self.rdp = rdp
        self.operation = operation

    def start_check(self) -> ActionCheck:
        """Check whether the RDP operation can be started."""
        if self.operation.rdp_id != self.rdp.pk:
            return ActionCheck(False, "RDP: operation does not belong to this RDP.")

        if self.rdp.status not in {Rdp.PushStatus.PENDING, Rdp.PushStatus.FAILURE}:
            return ActionCheck(False, f"RDP: can not start operation in status={self.rdp.status}.")

        if self.operation.status not in {RdpOperation.Status.PENDING, RdpOperation.Status.FAILURE}:
            return ActionCheck(
                False,
                f"RDP: can not start {self.operation.get_type_display()} in status={self.operation.status}.",
            )

        return ActionCheck(True)
