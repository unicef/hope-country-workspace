from collections.abc import Callable, Iterator
from functools import partial
from typing import Any
from django.db import transaction, IntegrityError

from country_workspace.contrib.dedup_engine import DeduplicationSetState, make_dedup_client, get_deduplication_status
from country_workspace.contrib.dedup_engine.deduplication_status import (
    CLONEABLE_DEDUPLICATION_SET_STATES,
    DedupResponseStatus,
)
from country_workspace.contrib.hope.exceptions import HopePushError
from country_workspace.exceptions import RemoteError
from country_workspace.models import AsyncJob, Rdp

from .processor import PushProcessor, DedupProcessor
from .config import CreateRdpConfig, PushWorkflowConfig
from .repository import (
    qs_individuals_by_pks,
    qs_individuals_by_household_pks,
    lock_rdp_for_update,
    qs_households,
    preflight_errors,
    preflight_exclude_rdp_ids,
    rdp_for_dedup,
    rdp_for_push,
    rdp_selection,
    selection_owner_for_rdp,
    set_rdp_push_status,
    workflow_config_for_rdp,
)


def create_rdp_records(config: CreateRdpConfig, job_id: int) -> Rdp:
    """Create an RDP and link beneficiaries."""
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
            AsyncJob.objects.filter(id=job_id).update(rdp=rdp)
            return rdp
    except IntegrityError as e:
        raise HopePushError({"errors": [f"RDP: can not create record: {e}"]}) from e


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
    if job.program.biometric_deduplication_enabled:
        try:
            with make_dedup_client(job.program.unicef_id) as client:
                can_create = client.can_create_deduplication_set()
        except RemoteError as e:
            raise HopePushError({"errors": [str(e)]}) from e
        if not can_create:
            raise HopePushError({"errors": ["DedupEngine: can not create deduplication set for this program."]})

    config: CreateRdpConfig = job.config
    errors = preflight_errors(
        pks=config["pks"],
        master_detail=config["master_detail"],
        exclude_rdp_ids=(),
    )
    if errors:
        raise HopePushError({"errors": errors})

    rdp = create_rdp_records(config, job.id)
    return {"rdp_id": rdp.id, "rdp_str": str(rdp)}


def clone_rdp_core(*, source: Rdp, batch_name: str, pushed_by_id: int) -> Rdp:
    """Create a child RDP that reuses the owner selection and DE deduplication set."""
    owner = selection_owner_for_rdp(rdp=source)

    if not owner.deduplication_set_id:
        raise HopePushError({"errors": ["DedupEngine: deduplication_set_id is not set for this RDP."]})

    status = get_deduplication_status(
        owner.program.unicef_id,
        str(owner.deduplication_set_id),
    )
    if status.response_status != DedupResponseStatus.OK:
        raise HopePushError({"errors": ["DedupEngine: can not retrieve deduplication set status."]})
    if status.deduplication_set_status not in CLONEABLE_DEDUPLICATION_SET_STATES:
        raise HopePushError(
            {
                "errors": [
                    "DedupEngine: can not clone RDP for deduplication set in "
                    f"state={status.deduplication_set_status!r}."
                ]
            }
        )

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

            pending_qs = Rdp.objects.filter(
                program_id=owner.program_id,
                status=Rdp.PushStatus.PENDING,
            )
            if source.status == Rdp.PushStatus.PENDING:
                pending_qs = pending_qs.exclude(pk=source.pk)
            if pending_qs.exists():
                raise HopePushError({"errors": ["RDP: can not clone while another RDP is pending"]})

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
                deduplication_set_id=owner.deduplication_set_id,
                hope_rdi_id="",
            )
    except IntegrityError as e:
        raise HopePushError({"errors": [f"RDP: can not clone record: {e}"]}) from e


def dedup_existing_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Run DedupEngine deduplication for an existing RDP."""
    processor = DedupProcessor(rdp_id=job.config["rdp_id"])
    processor.run()
    if processor.has_errors:
        raise HopePushError(processor.total)
    return processor.total


def reject_deduplication_set_existing_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Reject the active DedupEngine deduplication set for an existing RDP."""
    rdp = rdp_for_dedup(pk=job.config["rdp_id"])
    if rdp.status != Rdp.PushStatus.PENDING:
        raise HopePushError({"errors": [f"RDP: can not reject deduplication set in status={rdp.status}"]})
    if not rdp.program.biometric_deduplication_enabled:
        raise HopePushError({"errors": ["DedupEngine: biometric deduplication is not enabled for this program."]})
    if not rdp.deduplication_set_id:
        raise HopePushError({"errors": ["DedupEngine: deduplication_set_id is not set for this RDP."]})

    program_id = rdp.program.unicef_id
    deduplication_set_id = str(rdp.deduplication_set_id)

    try:
        with make_dedup_client(program_id, deduplication_set_id=deduplication_set_id) as client:
            payload = client.retrieve_deduplication_set()
            deduplication_set_state = payload.get("state")

            if deduplication_set_state != DeduplicationSetState.DEDUPLICATED:
                raise HopePushError(
                    {"errors": [f"DedupEngine: can not reject deduplication set in state={deduplication_set_state!r}."]}
                )

            client.reject()
    except RemoteError as e:
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
    if rdp.status != Rdp.PushStatus.PENDING:
        raise HopePushError({"errors": [f"RDP: can not push in status={rdp.status}"]})

    imported_by_email = getattr(job.owner, "email", "") or getattr(rdp.pushed_by, "email", "")
    config: PushWorkflowConfig = workflow_config_for_rdp(rdp=rdp, imported_by_email=imported_by_email)
    hope_processor = PushProcessor(config)

    for step in steps(hope_processor, config):
        step()
        if hope_processor.has_errors:
            with transaction.atomic():
                locked = lock_rdp_for_update(pk=rdp.pk)
                set_rdp_push_status(
                    rdp=locked, status=Rdp.PushStatus.FAILURE, hope_rdi_id=hope_processor.hope_rdi_id or "N/A"
                )
            raise HopePushError(hope_processor.total)

    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp.pk)
        mark_rdp_beneficiaries_removed(locked, config["master_detail"])
        set_rdp_push_status(rdp=locked, status=Rdp.PushStatus.SUCCESS, hope_rdi_id=hope_processor.hope_rdi_id or "N/A")

    return hope_processor.total
