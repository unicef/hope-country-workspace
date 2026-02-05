from collections.abc import Callable, Iterator
from functools import partial
from typing import Any
from django.db import transaction, IntegrityError

from country_workspace.contrib.hope.exceptions import HopePushError
from country_workspace.models import AsyncJob, Rdp
from country_workspace.workspaces.models import CountryIndividual
from country_workspace.contrib.dedup_engine.response import State as DedupResponseState


from .processor import PushProcessor, DedupProcessor
from .config import CreateRdpConfig, PushWorkflowConfig
from .repository import (
    individuals_by_pks,
    individuals_by_household_pks,
    mark_rdp_dedup_finished,
    households,
    rdp_for_push,
    preflight_errors,
    workflow_config_for_rdp,
)
from .transport import dedup_api


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


def complete_rdp(rdp_id: int, status: Rdp.PushStatus, hope_rdi_id: str) -> Rdp:
    """Update RDP status and hope_rdi_id atomically and return the updated record."""
    with transaction.atomic():
        rdp = Rdp.objects.select_for_update().get(id=rdp_id)
        rdp.status = status
        rdp.hope_rdi_id = hope_rdi_id
        rdp.save(update_fields=["status", "hope_rdi_id"])
        return rdp


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
            partial(processor.run_with, individuals_by_household_pks(pks), processor.rdi_push_individuals),
            partial(processor.run_with, households(pks=pks), processor.rdi_push_households),
        )
    else:
        yield partial(processor.run_with, individuals_by_pks(pks), processor.rdi_push_people)
    yield processor.rdi_complete


def create_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Create an RDP for the selected beneficiaries after passing preflight checks."""
    if job.program.beneficiary_group is None:
        raise HopePushError({"errors": ["RDP: beneficiary_group is not set"]})
    if not job.config.get("pks"):
        raise HopePushError({"errors": ["RDP: no beneficiaries selected"]})
    if job.program.biometric_deduplication_enabled:
        dedup_errors: list[str] = []
        with dedup_api(job.program.code, dedup_errors.append) as de:
            has = de.has_deduplication_set(reference_pk=job.program.code, state=DedupResponseState.READY)
            if has:
                raise HopePushError(
                    {
                        "errors": [
                            "DedupEngine: existing deduplication_set is still READY; "
                            "cannot create new RDP until previous deduplication is active."
                        ]
                    }
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
            complete_rdp(rdp.id, Rdp.PushStatus.FAILURE, hope_processor.hope_rdi_id or "N/A")
            raise HopePushError(hope_processor.total)

    if rdp.program.biometric_deduplication_enabled:
        mark_rdp_dedup_finished(rdp_id=rdp.pk)

    with transaction.atomic():
        updated = complete_rdp(rdp.id, Rdp.PushStatus.SUCCESS, hope_processor.hope_rdi_id)
        mark_rdp_beneficiaries_removed(updated, config["master_detail"])

    return hope_processor.total
