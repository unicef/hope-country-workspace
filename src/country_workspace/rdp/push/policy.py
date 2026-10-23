from country_workspace.models import Rdp
from country_workspace.rdp.operations.repository import has_incomplete_rdp_operations
from country_workspace.rdp.policy import ActionCheck, RdpActionPolicy


class PushPolicy(RdpActionPolicy):
    def review_push_check(self) -> ActionCheck:
        if self.rdp.program.cleanup_in_progress:
            return ActionCheck(False, "Program cleanup is in progress.")
        if self.rdp.status != Rdp.PushStatus.REVIEW_PENDING:
            return ActionCheck(False, f"RDP: can not push from review in status={self.rdp.status}")
        return ActionCheck(True)

    def retry_push_check(self) -> ActionCheck:
        if self.rdp.program.cleanup_in_progress:
            return ActionCheck(False, "Program cleanup is in progress.")
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
