import logging
from typing import Any

from country_workspace.models import AsyncJob, Batch
from country_workspace.workspaces.admin.cleaners.validate import create_validation_jobs

logger = logging.getLogger(__name__)


def reprocess_batch(job: AsyncJob) -> dict[str, Any]:
    batch_id = job.config.get("batch_id")
    if not batch_id:
        raise ValueError("batch_id is required in job config")

    batch = Batch.objects.select_related("program", "country_office").filter(pk=batch_id).first()
    if not batch:
        logger.error("Batch %s not found", batch_id)
        raise Batch.DoesNotExist(f"Batch {batch_id} not found")

    household_count = batch.household_set.count()
    individual_count = batch.individual_set.filter(household=None).count()

    validation_jobs_created = 0

    if household_count > 0:
        queryset = batch.household_set.all().prefetch_related("members")
        create_validation_jobs(
            description=f"Reprocess batch {batch.name} - Households",
            owner=job.owner,
            program=batch.program,
            queryset=queryset,
        )
        validation_jobs_created += 1

    # If batch has individuals without households, validate them
    if individual_count > 0:
        queryset = batch.individual_set.filter(household=None)
        create_validation_jobs(
            description=f"Reprocess batch {batch.name} - Individuals",
            owner=job.owner,
            program=batch.program,
            queryset=queryset,
        )
        validation_jobs_created += 1

    result = {
        "batch_id": batch_id,
        "batch_name": batch.name,
        "households": household_count,
        "individuals": individual_count,
        "validation_jobs_created": validation_jobs_created,
    }

    logger.info("Batch reprocessing initiated: %s", result)
    return result
