from collections.abc import Callable, Iterator
from functools import partial
from typing import Any

from django.db import transaction


from country_workspace.contrib.hope.exceptions import HopePushError
from country_workspace.models import AsyncJob, Rdp
from country_workspace.workspaces.models import CountryIndividual


from .config import PushConfig, WorkflowConfig
from .processor import PushProcessor
from .repository import individuals_by_pks, individuals_by_household_pks, households


def create_rdp_records(config: PushConfig, job_id: int) -> int:
    """Create an RDP and link beneficiaries."""
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
        return rdp.id


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


def steps(processor: PushProcessor, config: WorkflowConfig) -> Iterator[Callable[[], None]]:
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


def push_to_hope_core(job: AsyncJob) -> dict[str, Any]:
    """Run the push workflow for a job; raise HopePushError on step failure."""
    if job.program.beneficiary_group is None:
        return {"errors": ["RDI - beneficiary_group is not set"]}
    if not job.config.get("pks"):
        return {"errors": ["RDI - no beneficiaries to push"]}

    rdp_id = create_rdp_records(job.config, job.id)
    config: WorkflowConfig = {**job.config, "rdp_id": rdp_id}
    processor = PushProcessor(config)

    for step in steps(processor, config):
        step()
        if processor.total["errors"]:
            complete_rdp(rdp_id, Rdp.PushStatus.FAILURE, processor.hope_rdi_id or "N/A")
            raise HopePushError(processor.total)

    with transaction.atomic():
        rdp = complete_rdp(rdp_id, Rdp.PushStatus.SUCCESS, processor.hope_rdi_id)
        mark_rdp_beneficiaries_removed(rdp, config["master_detail"])

    return processor.total
