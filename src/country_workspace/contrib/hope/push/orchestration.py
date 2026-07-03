from collections.abc import Callable, Iterator
from functools import partial
from typing import Any
from uuid import UUID, uuid4

from django.db import IntegrityError, transaction

from country_workspace.contrib.dedup_engine import REJECTABLE_DEDUPLICATION_SET_STATES, make_dedup_client
from country_workspace.contrib.hope.exceptions import HopePushError
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import AsyncJob, Rdp

from .config import CreateRdpConfig, OperationLogResult, PushWorkflowConfig
from .policy import ActionCheck, get_rdp_policy
from .processor import DedupProcessor, PushProcessor
from .repository import (
    append_rdp_operation_log,
    lock_rdp_for_update,
    preflight_errors,
    qs_households,
    qs_individuals_by_household_pks,
    qs_individuals_by_pks,
    rdp_for_dedup,
    rdp_for_push,
    release_rdp_dedup_settings_lock,
    release_rdp_push_lock,
    set_rdp_push_status,
    workflow_config_for_rdp,
)


def _require_policy_check(check: Callable[[], ActionCheck]) -> None:
    try:
        check().require()
    except (RemoteError, RemoteUnavailableError) as e:
        raise HopePushError({"errors": [str(e)]}) from e


def create_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Create an RDP for the selected beneficiaries after passing preflight checks."""
    if job.program.beneficiary_group is None:
        raise HopePushError({"errors": ["RDP: beneficiary_group is not set"]})

    config: CreateRdpConfig = job.config
    errors = preflight_errors(
        pks=config["pks"],
        master_detail=config["master_detail"],
        exclude_rdp_ids=(),
    )
    if errors:
        raise HopePushError({"errors": errors})

    if job.program.biometric_deduplication_enabled:
        try:
            with make_dedup_client(job.program.unicef_id) as client:
                if not client.can_create_deduplication_set():
                    raise HopePushError({"errors": ["DedupEngine: can not create deduplication set for this program."]})
        except (RemoteError, RemoteUnavailableError) as e:
            raise HopePushError({"errors": [str(e)]}) from e

    try:
        with transaction.atomic():
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
        if "uniq_open_rdp_per_program" in str(e):
            message = "RDP: can not create while another RDP is open"
        raise HopePushError({"errors": [message]}) from e

    return {"rdp_id": rdp.id, "rdp_str": str(rdp)}


def claim_rdp_deduplication(rdp_id: int) -> tuple[ActionCheck, Rdp | None]:
    rdp = rdp_for_dedup(pk=rdp_id)
    policy = get_rdp_policy(rdp)
    check = policy.deduplicate_check()
    if not check.allowed:
        return check, None

    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp_id)
        if locked.is_dedup_settings_locked:
            return ActionCheck(False, "RDP: deduplication has already been started for this RDP."), None

        update_fields = ["is_dedup_settings_locked"]
        locked.is_dedup_settings_locked = True
        if policy.can_create_deduplication_set and not locked.deduplication_set_id:
            locked.deduplication_set_id = uuid4()
            update_fields.append("deduplication_set_id")

        locked.save(update_fields=update_fields)

    return ActionCheck(True), locked


def claim_rdp_push(rdp_id: int) -> tuple[ActionCheck, Rdp | None]:
    """Claim an RDP push by setting a local push lock."""
    rdp = rdp_for_push(pk=rdp_id)
    check = get_rdp_policy(rdp).start_push_check()
    if not check.allowed:
        return check, None

    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp_id)

        if locked.is_push_locked:
            return ActionCheck(False, "RDP: push to HOPE is already queued or running."), None
        if locked.status not in {locked.PushStatus.PENDING, locked.PushStatus.FAILURE}:
            return ActionCheck(False, f"RDP: can not push in status={locked.status}"), None

        locked.is_push_locked = True
        locked.save(update_fields=["is_push_locked"])

    return ActionCheck(True), locked


def dedup_existing_rdp_core(job: AsyncJob) -> dict[str, Any]:
    rdp_id = job.config["rdp_id"]
    rdp = rdp_for_dedup(pk=rdp_id)

    try:
        _require_policy_check(get_rdp_policy(rdp).deduplicate_check)

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
            append_rdp_operation_log(
                rdp=locked,
                action=Rdp.OperationAction.START_DEDUPLICATION,
                job_id=job.pk,
                result=result,
            )

        if processor.has_errors:
            raise HopePushError(processor.total)
        return processor.total

    finally:
        release_rdp_dedup_settings_lock(rdp_id=rdp_id)


def cancel_existing_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Cancel an existing RDP and reject its active DedupEngine set when required."""
    rdp = rdp_for_dedup(pk=job.config["rdp_id"])
    policy = get_rdp_policy(rdp)
    _require_policy_check(policy.cancel_check)

    group_reference_id = rdp.program.unicef_id
    deduplication_set_id = str(rdp.deduplication_set_id) if rdp.deduplication_set_id else None
    dedup_engine_rejected = False

    if deduplication_set_id and policy.deduplication_set_state in REJECTABLE_DEDUPLICATION_SET_STATES:
        try:
            with make_dedup_client(group_reference_id, deduplication_set_id=deduplication_set_id) as client:
                client.reject()
        except (RemoteError, RemoteUnavailableError) as e:
            raise HopePushError({"errors": [str(e)]}) from e
        dedup_engine_rejected = True

    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp.pk)
        set_rdp_push_status(
            rdp=locked,
            status=Rdp.PushStatus.CANCELLED,
            hope_rdi_id=locked.hope_rdi_id or "N/A",
            is_dedup_settings_locked=False,
            is_push_locked=False,
        )

    return {
        "rdp_id": rdp.pk,
        "program": group_reference_id,
        "deduplication_set_id": deduplication_set_id,
        "dedup_engine_rejected": dedup_engine_rejected,
        "cancelled": True,
    }


def _mark_rdp_beneficiaries_removed(rdp: Rdp, is_master_detail: bool) -> None:
    """Mark RDP beneficiaries as removed."""
    if is_master_detail:
        hh_ids = list(rdp.households.values_list("pk", flat=True))
        if not hh_ids:
            return
        rdp.households.update(removed=True)
        qs_individuals_by_household_pks(hh_ids).update(removed=True)
        return
    rdp.individuals.update(removed=True)


def _steps(processor: PushProcessor, config: PushWorkflowConfig) -> Iterator[Callable[[], None]]:
    """Yield the ordered workflow callables; each step appends errors to processor.total."""
    pks = config["pks"]

    yield processor.preflight
    yield processor.rdi_create
    if config["master_detail"]:
        yield from (
            partial(processor.run_with, qs_individuals_by_household_pks(pks), processor.rdi_push_individuals),
            partial(processor.run_with, qs_households(pks=pks), processor.rdi_push_households),
        )
    else:
        yield partial(processor.run_with, qs_individuals_by_pks(pks), processor.rdi_push_people)
    yield processor.rdi_complete


def push_existing_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Run the push workflow for an existing RDP."""
    rdp_id = job.config["rdp_id"]
    rdp = rdp_for_push(pk=rdp_id)

    try:
        _require_policy_check(get_rdp_policy(rdp).push_check)
        imported_by_email = getattr(job.owner, "email", "") or getattr(rdp.pushed_by, "email", "")
        config: PushWorkflowConfig = workflow_config_for_rdp(rdp=rdp, imported_by_email=imported_by_email)
        hope_processor = PushProcessor(config)

        for step in _steps(hope_processor, config):
            step()
            if hope_processor.has_errors:
                with transaction.atomic():
                    locked = lock_rdp_for_update(pk=rdp.pk)
                    set_rdp_push_status(
                        rdp=locked,
                        status=Rdp.PushStatus.FAILURE,
                        hope_rdi_id=hope_processor.hope_rdi_id or "N/A",
                        is_push_locked=False,
                    )
                raise HopePushError(hope_processor.total)

        with transaction.atomic():
            locked = lock_rdp_for_update(pk=rdp.pk)
            _mark_rdp_beneficiaries_removed(locked, config["master_detail"])
            set_rdp_push_status(
                rdp=locked,
                status=Rdp.PushStatus.SUCCESS,
                hope_rdi_id=hope_processor.hope_rdi_id or "N/A",
                is_push_locked=False,
            )
            group_reference_id = locked.program.unicef_id
            deduplication_set_id = locked.deduplication_set_id

        _approve_deduplication_set_after_successful_push(
            group_reference_id=group_reference_id,
            deduplication_set_id=deduplication_set_id,
            processor=hope_processor,
        )
        return hope_processor.total

    finally:
        release_rdp_push_lock(rdp_id=rdp_id)


def _approve_deduplication_set_after_successful_push(
    group_reference_id: str,
    deduplication_set_id: UUID | None,
    processor: PushProcessor,
) -> None:
    """Approve the active DedupEngine deduplication set after a successful push to HOPE Core."""
    if not deduplication_set_id:
        return

    try:
        with make_dedup_client(
            group_reference_id,
            deduplication_set_id=str(deduplication_set_id),
        ) as client:
            client.approve()
    except (RemoteError, RemoteUnavailableError) as e:
        processor.fail("DedupEngine", f"approve failed. {e}")
