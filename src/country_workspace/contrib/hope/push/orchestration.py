from collections.abc import Callable, Iterator
from functools import partial
from typing import Any

from django.db import IntegrityError, transaction

from country_workspace.contrib.dedup_engine import make_dedup_client
from country_workspace.contrib.hope.exceptions import HopePushError
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import AsyncJob, Rdp

from .config import CreateRdpConfig, PushWorkflowConfig
from .policy import ActionCheck, get_rdp_policy
from .processor import DedupProcessor, PushProcessor
from .repository import (
    has_other_pending_rdp,
    lock_rdp_for_update,
    preflight_errors,
    preflight_exclude_rdp_ids,
    qs_households,
    qs_individuals_by_household_pks,
    qs_individuals_by_pks,
    rdp_for_dedup,
    rdp_for_push,
    rdp_selection,
    selection_owner_for_rdp,
    set_rdp_push_status,
    set_rdp_deduplication_snapshot,
    workflow_config_for_rdp,
)


def require_policy_check(check: Callable[[], ActionCheck]) -> None:
    try:
        check().require()
    except (RemoteError, RemoteUnavailableError) as e:
        raise HopePushError({"errors": [str(e)]}) from e


def claim_rdp_deduplication(rdp_id: int) -> tuple[ActionCheck, Rdp | None]:
    """Validate and mark RDP deduplication as requested inside an active transaction."""
    rdp = lock_rdp_for_update(pk=rdp_id)
    if rdp.is_deduplication_started:
        return ActionCheck(False, "RDP: deduplication has already been started for this RDP."), None
    check = get_rdp_policy(rdp).deduplicate_check()
    if not check.allowed:
        return check, None
    rdp.is_deduplication_started = True
    rdp.save(update_fields=["is_deduplication_started"])
    return ActionCheck(True), rdp


def deduplication_snapshot(rdp: Rdp) -> dict[str, Any]:
    """Return the current deduplication snapshot for the given RDP."""
    if (status := get_rdp_policy(rdp).deduplication_status(rdp)) is None:
        return {}
    return {
        "deduplication_set_status": (
            status.deduplication_set_status.value
            if hasattr(status.deduplication_set_status, "value")
            else status.deduplication_set_status
        ),
        "findings_count": status.findings_count,
    }


def mark_rdp_beneficiaries_removed(rdp: Rdp, is_master_detail: bool) -> None:
    """Mark selection-owner beneficiaries as removed."""
    owner = selection_owner_for_rdp(rdp=rdp)
    if is_master_detail:
        hh_ids = list(owner.households.values_list("pk", flat=True))
        if not hh_ids:
            return
        owner.households.update(removed=True)
        qs_individuals_by_household_pks(hh_ids).update(removed=True)
        return
    owner.individuals.update(removed=True)


def steps(processor: PushProcessor, config: PushWorkflowConfig) -> Iterator[Callable[[], None]]:
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


def create_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Create an RDP for the selected beneficiaries after passing preflight checks."""
    if job.program.beneficiary_group is None:
        raise HopePushError({"errors": ["RDP: beneficiary_group is not set"]})
    if not job.config.get("pks"):
        raise HopePushError({"errors": ["RDP: no beneficiaries selected"]})

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
        raise HopePushError({"errors": [f"RDP: can not create record: {e}"]}) from e

    return {"rdp_id": rdp.id, "rdp_str": str(rdp)}


def clone_rdp_core(*, source: Rdp, batch_name: str, pushed_by_id: int) -> Rdp:
    """Create a child RDP that reuses the owner selection and starts a new deduplication lifecycle."""
    require_policy_check(get_rdp_policy(source).clone_check)

    owner = selection_owner_for_rdp(rdp=source)
    master_detail, pks = rdp_selection(rdp=owner)
    errors = preflight_errors(
        pks=pks,
        master_detail=master_detail,
        exclude_rdp_ids=preflight_exclude_rdp_ids(rdp=source),
    )
    if errors:
        raise HopePushError({"errors": errors})

    try:
        with transaction.atomic():
            source = lock_rdp_for_update(pk=source.pk)
            owner = selection_owner_for_rdp(rdp=source)
            if owner.pk != source.pk:
                owner = lock_rdp_for_update(pk=owner.pk)

            exclude_ids = (source.pk,) if source.status == Rdp.PushStatus.PENDING else ()
            if has_other_pending_rdp(owner=owner, exclude_ids=exclude_ids):
                raise HopePushError({"errors": ["RDP: can not clone while another RDP is pending"]})

            set_rdp_deduplication_snapshot(
                rdp=source,
                key="before_clone",
                snapshot=deduplication_snapshot(source),
            )

            if source.status == Rdp.PushStatus.PENDING:
                source.status = Rdp.PushStatus.CANCELLED
                source.save(update_fields=["status"])

            return Rdp.objects.create(
                country_office_id=owner.country_office_id,
                program_id=owner.program_id,
                pushed_by_id=pushed_by_id,
                name=batch_name,
                parent=owner,
                status=Rdp.PushStatus.PENDING,
                deduplication_set_id=None,
                hope_rdi_id="",
            )
    except IntegrityError as e:
        raise HopePushError({"errors": [f"RDP: can not clone record: {e}"]}) from e


def dedup_existing_rdp_core(job: AsyncJob) -> dict[str, Any]:
    rdp = rdp_for_dedup(pk=job.config["rdp_id"])
    require_policy_check(get_rdp_policy(rdp).deduplicate_check)

    processor = DedupProcessor(rdp)
    processor.run()
    if processor.has_errors:
        raise HopePushError(processor.total)
    return processor.total


def reject_deduplication_set_existing_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Reject the active DedupEngine deduplication set for an existing RDP."""
    rdp = rdp_for_dedup(pk=job.config["rdp_id"])
    require_policy_check(get_rdp_policy(rdp).reject_ds_check)

    program_id = rdp.program.unicef_id
    deduplication_set_id = str(rdp.deduplication_set_id)

    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp.pk)
        set_rdp_deduplication_snapshot(
            rdp=locked,
            key="before_reject",
            snapshot=deduplication_snapshot(locked),
        )

    try:
        with make_dedup_client(program_id, deduplication_set_id=deduplication_set_id) as client:
            client.reject()
    except (RemoteError, RemoteUnavailableError) as e:
        raise HopePushError({"errors": [str(e)]}) from e

    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp.pk)
        set_rdp_push_status(
            rdp=locked,
            status=Rdp.PushStatus.CANCELLED,
            hope_rdi_id=locked.hope_rdi_id or "N/A",
        )

    return {
        "rdp_id": rdp.pk,
        "program": program_id,
        "deduplication_set_id": deduplication_set_id,
        "rejected": True,
    }


def push_existing_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Run the push workflow for an existing RDP."""
    rdp = rdp_for_push(pk=job.config["rdp_id"])
    require_policy_check(get_rdp_policy(rdp).push_check)

    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp.pk)
        set_rdp_deduplication_snapshot(
            rdp=locked,
            key="before_push",
            snapshot=deduplication_snapshot(locked),
        )

    imported_by_email = getattr(job.owner, "email", "") or getattr(rdp.pushed_by, "email", "")
    config: PushWorkflowConfig = workflow_config_for_rdp(rdp=rdp, imported_by_email=imported_by_email)
    hope_processor = PushProcessor(config)

    for step in steps(hope_processor, config):
        step()
        if hope_processor.has_errors:
            with transaction.atomic():
                locked = lock_rdp_for_update(pk=rdp.pk)
                set_rdp_push_status(
                    rdp=locked,
                    status=Rdp.PushStatus.FAILURE,
                    hope_rdi_id=hope_processor.hope_rdi_id or "N/A",
                )
            raise HopePushError(hope_processor.total)

    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp.pk)
        mark_rdp_beneficiaries_removed(locked, config["master_detail"])
        set_rdp_push_status(
            rdp=locked,
            status=Rdp.PushStatus.SUCCESS,
            hope_rdi_id=hope_processor.hope_rdi_id or "N/A",
        )

    return hope_processor.total
