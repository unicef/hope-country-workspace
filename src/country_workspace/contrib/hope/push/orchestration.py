from collections.abc import Callable, Iterator
from functools import partial
from typing import Any
from django.db import transaction, IntegrityError

from country_workspace.contrib.dedup_engine.client import make_client as make_dedup_client
from country_workspace.contrib.dedup_engine.response import Status as DedupResponseStatus
from country_workspace.contrib.hope.exceptions import HopePushError
from country_workspace.exceptions import RemoteError
from country_workspace.models import AsyncJob, Rdp
from country_workspace.workspaces.models import CountryIndividual

from .processor import PushProcessor, DedupProcessor
from .config import CreateRdpConfig, PushWorkflowConfig
from .repository import (
    qs_individuals_by_pks,
    qs_individuals_by_household_pks,
    lock_rdp_for_update,
    qs_households,
    preflight_errors,
    rdp_for_dedup,
    rdp_for_push,
    set_rdp_dedup_state,
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
    """Mark RDP-related beneficiaries as removed."""
    if is_master_detail:
        rdp.households.update(removed=True)
        CountryIndividual.objects.filter(household__rdp=rdp).update(removed=True)
    else:
        rdp.individuals.update(removed=True)


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
                res = client.status()
        except RemoteError as e:
            raise HopePushError({"errors": [str(e)]}) from e

        if res.status is not DedupResponseStatus.DS_NOT_EXPOSED:
            raise HopePushError(
                {"errors": ["DedupEngine: there is an existing non-inactive deduplication set for this program."]}
            )

    config: CreateRdpConfig = job.config
    errors = preflight_errors(
        pks=config["pks"],
        master_detail=config["master_detail"],
        exclude_rdp_id=None,
    )
    if errors:
        raise HopePushError({"errors": errors})

    rdp = create_rdp_records(config, job.id)
    return {"rdp_id": rdp.id, "rdp_str": str(rdp)}


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
    if not rdp.program.biometric_deduplication_enabled:
        raise HopePushError({"errors": ["DedupEngine: biometric deduplication is not enabled for this program."]})
    if not rdp.deduplication_set_id:
        raise HopePushError({"errors": ["DedupEngine: deduplication_set_id is not set for this RDP."]})

    program_id, deduplication_set_id = rdp.program.unicef_id, str(rdp.deduplication_set_id)

    try:
        with make_dedup_client(program_id) as client:
            status = client.status().status
            rejected = status is not DedupResponseStatus.DS_NOT_EXPOSED
            if rejected:
                client.reject()
    except RemoteError as e:
        raise HopePushError({"errors": [str(e)]}) from e

    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp.pk)
        set_rdp_dedup_state(rdp_id=locked.pk, state=Rdp.DedupRunState.FINISHED)
        set_rdp_push_status(
            rdp=locked,
            status=Rdp.PushStatus.CANCELLED if rejected else locked.status,
            hope_rdi_id=locked.hope_rdi_id or "N/A",
        )

    return {
        "rdp_id": rdp.pk,
        "program": program_id,
        "deduplication_set_id": deduplication_set_id,
        "status": DedupResponseStatus.DS_NOT_EXPOSED.value if rejected else status.value,
        "rejected": rejected,
    }


def push_existing_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Run the push workflow for an existing RDP."""
    rdp_id = job.config["rdp_id"]

    rdp = rdp_for_push(pk=rdp_id)
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

        if locked.program.biometric_deduplication_enabled:
            set_rdp_dedup_state(rdp_id=locked.pk, state=Rdp.DedupRunState.FINISHED)

        set_rdp_push_status(rdp=locked, status=Rdp.PushStatus.SUCCESS, hope_rdi_id=hope_processor.hope_rdi_id or "N/A")

    return hope_processor.total
