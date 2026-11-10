from django.db import transaction

from country_workspace.rdp.policy import ActionCheck, get_rdp_policy
from country_workspace.rdp.repository import lock_rdp_for_update, set_rdp_beneficiaries_removed


def reset_rdp(*, rdp_id: int) -> ActionCheck:
    """Reset the latest successful RDP."""
    with transaction.atomic():
        rdp = lock_rdp_for_update(pk=rdp_id)
        check = get_rdp_policy(rdp).reset_check()
        if not check.allowed:
            return check

        set_rdp_beneficiaries_removed(rdp=rdp, removed=False)
        rdp.mark_cancelled()

    return ActionCheck(True)
