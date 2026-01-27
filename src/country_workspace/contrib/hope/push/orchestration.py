from collections.abc import Callable, Iterator
from functools import partial
from typing import Any
from requests.exceptions import RequestException
from uuid import UUID
from django.db import transaction, IntegrityError

from country_workspace.contrib.hope.exceptions import HopePushError
from country_workspace.contrib.hope.constants import IMAGES_TO_DEDUPLICATE_BULK_BATCH_SIZE
from country_workspace.models import AsyncJob, Rdp
from country_workspace.workspaces.models import CountryIndividual
from country_workspace.contrib.dedup_engine.client import Status as DedupClientStatus, make_client
from country_workspace.contrib.dedup_engine.response import Status as DedupResponseStatus


from .processor import PushProcessor
from .config import CreateRdpConfig, PushWorkflowConfig
from .repository import (
    individuals_by_pks,
    individuals_for_rdp,
    individuals_by_household_pks,
    households,
    rdp_for_push,
    rdp_for_dedup,
    preflight_errors,
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


def dedup_engine_status_or_error(program_code: str) -> DedupClientStatus:
    """Fetch DedupEngine status or raise HopePushError."""
    try:
        with make_client(program_code) as client:
            return client.status()
    except (RequestException, ValueError) as e:
        raise HopePushError({"errors": [f"DedupEngine: status() failed: {e}"]}) from e


def dedup_engine_approve_or_error(program_code: str) -> None:
    """Approve DedupEngine results or raise HopePushError."""
    try:
        with make_client(program_code) as client:
            client.approve()
    except (RequestException, ValueError) as e:
        raise HopePushError({"errors": [f"DedupEngine: approve() failed: {e}"]}) from e


def _parse_uuid(value: object) -> UUID | None:
    """Return UUID parsed from value or None if parsing fails."""
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _collect_dedup_images(*, rdp: Rdp) -> tuple[list[dict[str, str]], int]:
    """Collect DedupEngine images payload (reference_pk, filename) from RDP individuals."""
    rows = individuals_for_rdp(rdp=rdp).values_list("pk", "flex_fields__photo")

    images: list[dict[str, str]] = []
    skipped = 0
    for pk, photo in rows.iterator(chunk_size=IMAGES_TO_DEDUPLICATE_BULK_BATCH_SIZE * 5):
        if isinstance(photo, str) and (photo := photo.strip()):
            images.append({"reference_pk": str(pk), "filename": photo})
        else:
            skipped += 1
    return images, skipped


def _dedup_engine_create_set_or_error(*, program_code: str) -> UUID:
    """Create a DedupEngine deduplication set and return its UUID."""
    try:
        with make_client(program_code) as client:
            ds_id = client.create_deduplication_set(settings={})
    except (RequestException, ValueError, KeyError, TypeError) as e:
        raise HopePushError({"errors": [f"DedupEngine: create_deduplication_set() failed: {e}"]}) from e

    if (dedup_uuid := _parse_uuid(ds_id)) is None:
        raise HopePushError({"errors": [f"DedupEngine: invalid deduplication_set_id={ds_id!r}"]})
    return dedup_uuid


def _dedup_engine_upload_and_process_or_error(*, program_code: str, images: list[dict[str, str]]) -> None:
    """Upload images to DedupEngine and start processing."""
    try:
        with make_client(program_code) as client:
            client.create_images(images)
            client.process()
    except (RequestException, ValueError, KeyError, TypeError) as e:
        raise HopePushError({"errors": [f"DedupEngine: create_images()/process() failed: {e}"]}) from e


def dedup_existing_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Run DedupEngine deduplication for an existing RDP."""
    rdp = rdp_for_dedup(pk=job.config["rdp_id"])
    if rdp.status != Rdp.PushStatus.PENDING:
        raise HopePushError({"errors": [f"RDP: can not run dedup in status={rdp.status}"]})
    if rdp.dedup_run_state == rdp.DedupRunState.APPROVED:
        raise HopePushError({"errors": ["RDP: can not run dedup after approval"]})

    images, skipped = _collect_dedup_images(rdp=rdp)
    total = {
        "rdp_id": rdp.pk,
        "program": rdp.program.code,
        "skipped_no_photo": skipped,
        "images_sent": len(images),
    }
    if not images:
        return total | {"deduplication_set_id": None}

    deduplication_set_id = _dedup_engine_create_set_or_error(program_code=rdp.program.code)

    Rdp.objects.filter(pk=rdp.pk).update(
        deduplication_set_id=deduplication_set_id,
        dedup_run_state=rdp.DedupRunState.IN_PROGRESS,
    )

    _dedup_engine_upload_and_process_or_error(program_code=rdp.program.code, images=images)

    return total | {"deduplication_set_id": str(deduplication_set_id)}


def push_existing_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Run the push workflow for an existing RDP."""
    rdp_id = job.config["rdp_id"]

    rdp = rdp_for_push(pk=rdp_id)
    imported_by_email = getattr(job.owner, "email", "") or getattr(rdp.pushed_by, "email", "")

    config: PushWorkflowConfig = workflow_config_for_rdp(rdp=rdp, imported_by_email=imported_by_email)
    processor = PushProcessor(config)
    for step in steps(processor, config):
        step()
        if processor.total["errors"]:
            complete_rdp(rdp.id, Rdp.PushStatus.FAILURE, processor.hope_rdi_id or "N/A")
            raise HopePushError(processor.total)

    program_code = rdp.program.code
    if rdp.dedup_run_state == Rdp.DedupRunState.IN_PROGRESS:
        try:
            if dedup_engine_status_or_error(program_code).status == DedupResponseStatus.SUCCESS:
                dedup_engine_approve_or_error(program_code)
                Rdp.objects.filter(pk=rdp.pk).update(dedup_run_state=Rdp.DedupRunState.APPROVED)
        except HopePushError:
            complete_rdp(rdp.id, Rdp.PushStatus.FAILURE, processor.hope_rdi_id or "N/A")
            raise

    with transaction.atomic():
        updated = complete_rdp(rdp.id, Rdp.PushStatus.SUCCESS, processor.hope_rdi_id)
        mark_rdp_beneficiaries_removed(updated, config["master_detail"])

    return processor.total
