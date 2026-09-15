from typing import TYPE_CHECKING, Any
from uuid import uuid4

from django.db import transaction

from country_workspace.contrib.dedup_engine import make_dedup_client
from country_workspace.models import AsyncJob, Rdp
from country_workspace.models.rdp import RdpOperationAction
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.policy import ActionCheck, get_rdp_policy, require_policy_check
from country_workspace.rdp.repository import append_rdp_operation_log, lock_rdp_for_update

from .processor import DedupProcessor
from .repository import release_rdp_dedup_settings_lock, rdp_for_dedup

if TYPE_CHECKING:
    from country_workspace.rdp.types import OperationLogResult


def claim_rdp_deduplication(rdp_id: int) -> tuple[ActionCheck, Rdp | None]:
    rdp = rdp_for_dedup(pk=rdp_id)
    policy = get_rdp_policy(rdp)
    check = policy.claim_deduplication_check()
    if not check.allowed:
        return check, None

    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp_id)
        if locked.status not in {Rdp.PushStatus.PENDING, Rdp.PushStatus.FAILURE}:
            return ActionCheck(False, f"RDP: can not run dedup in status={locked.status}"), None
        if locked.is_dedup_settings_locked:
            return ActionCheck(False, "RDP: deduplication has already been started for this RDP."), None

        update_fields = ["is_dedup_settings_locked"]
        locked.is_dedup_settings_locked = True
        if policy.can_create_deduplication_set and not locked.deduplication_set_id:
            locked.deduplication_set_id = uuid4()
            update_fields.append("deduplication_set_id")
        locked.save(update_fields=update_fields)

    return ActionCheck(True), locked


def dedup_existing_rdp_core(job: AsyncJob) -> dict[str, Any]:
    rdp_id = job.config["rdp_id"]
    rdp = rdp_for_dedup(pk=rdp_id)

    try:
        require_policy_check(get_rdp_policy(rdp).deduplicate_check)

        with make_dedup_client(rdp.program.unicef_id) as client:
            dedup_settings = client.get_deduplication_set_group_config()

        processor = DedupProcessor(rdp)
        processor.run()
        result: OperationLogResult = {
            "images_sent": processor.total["images_sent"],
            "dedup_settings": dedup_settings,
            "deduplication_set_id": str(processor.rdp.deduplication_set_id)
            if processor.rdp.deduplication_set_id
            else None,
        }

        with transaction.atomic():
            locked = lock_rdp_for_update(pk=rdp.pk)
            append_rdp_operation_log(rdp=locked, action=RdpOperationAction.START_DEDUPLICATION, result=result)

        if processor.has_errors:
            raise RdpWorkflowError(processor.total)
        return {"rdp_id": rdp_id, "images_sent": processor.total["images_sent"]}

    finally:
        release_rdp_dedup_settings_lock(rdp_id=rdp_id)
