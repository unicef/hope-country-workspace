from typing import Any, TYPE_CHECKING
from django.db import IntegrityError, transaction

from country_workspace.contrib.dedup_engine import REJECTABLE_DEDUPLICATION_SET_STATES, make_dedup_client
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import AsyncJob, Program, Rdp

from country_workspace.rdp.deduplication.operations import reject_deduplication_set
from .exceptions import RdpWorkflowError
from .policy import ActionCheck, get_rdp_policy, require_policy_check
from .repository import (
    lock_rdp_for_update,
    set_rdp_beneficiaries_removed,
)
from .validation import preflight_errors


if TYPE_CHECKING:
    from .types import CreateRdpConfig


def create_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Create an RDP for the selected beneficiaries after passing preflight checks."""
    if job.program.beneficiary_group is None:
        raise RdpWorkflowError({"errors": ["RDP: beneficiary_group is not set"]})

    config: CreateRdpConfig = job.config
    errors = preflight_errors(pks=config["pks"], master_detail=config["master_detail"], exclude_rdp_ids=())
    if errors:
        raise RdpWorkflowError({"errors": errors})

    if job.program.biometric_deduplication_enabled:
        try:
            with make_dedup_client(job.program.unicef_id) as client:
                if not client.can_create_deduplication_set():
                    raise RdpWorkflowError(
                        {"errors": ["DedupEngine: can not create deduplication set for this program."]}
                    )
        except (RemoteError, RemoteUnavailableError) as e:
            raise RdpWorkflowError({"errors": [str(e)]}) from e

    try:
        with transaction.atomic():
            Program.objects.select_for_update().get(pk=config["program_id"])
            rdp = Rdp.objects.create(
                country_office_id=config["country_office_id"],
                program_id=config["program_id"],
                name=config["batch_name"],
                pushed_by_id=config["pushed_by_id"],
                status=Rdp.PushStatus.PENDING,
            )
            rdp.add_beneficiaries(config["pks"], config["master_detail"])
            AsyncJob.objects.filter(id=job.id).update(rdp=rdp)
    except IntegrityError as e:
        message = "RDP: can not create record"
        if "uniq_non_terminal_rdp_per_program" in str(e):
            message = "RDP: can not create while another RDP is unfinished"
        raise RdpWorkflowError({"errors": [message]}) from e

    return {"rdp_id": rdp.id}


def _mark_rdp_cancelled(*, rdp: Rdp) -> None:
    """Mark an already-locked RDP as cancelled."""
    rdp.status = Rdp.PushStatus.CANCELLED
    rdp.hope_rdi_id = rdp.hope_rdi_id or "N/A"
    rdp.is_dedup_settings_locked = False
    rdp.push_attempt_id = None
    rdp.save(update_fields=["status", "hope_rdi_id", "is_dedup_settings_locked", "push_attempt_id"])


def reset_rdp(*, rdp_id: int) -> ActionCheck:
    """Reset the latest successful RDP."""
    with transaction.atomic():
        rdp = lock_rdp_for_update(pk=rdp_id)
        check = get_rdp_policy(rdp).reset_check()
        if not check.allowed:
            return check

        set_rdp_beneficiaries_removed(rdp=rdp, removed=False)
        _mark_rdp_cancelled(rdp=rdp)

    return ActionCheck(True)


def cancel_existing_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Cancel an existing RDP and reject its active DedupEngine set when required."""
    rdp_id = job.config["rdp_id"]

    with transaction.atomic():
        rdp = lock_rdp_for_update(pk=rdp_id)
        policy = get_rdp_policy(rdp)
        require_policy_check(policy.cancel_check)

        group_reference_id = rdp.program.unicef_id
        deduplication_set_id = str(rdp.deduplication_set_id) if rdp.deduplication_set_id else None
        dedup_engine_rejected = False

        if deduplication_set_id and policy.deduplication_set_state in REJECTABLE_DEDUPLICATION_SET_STATES:
            try:
                reject_deduplication_set(
                    group_reference_id=group_reference_id, deduplication_set_id=deduplication_set_id
                )
            except (RemoteError, RemoteUnavailableError) as exc:
                raise RdpWorkflowError({"errors": [str(exc)]}) from exc

            dedup_engine_rejected = True

        _mark_rdp_cancelled(rdp=rdp)

    return {"rdp_id": rdp_id, "deduplication_set_rejected": dedup_engine_rejected}
