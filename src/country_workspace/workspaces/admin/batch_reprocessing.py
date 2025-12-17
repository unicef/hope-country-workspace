import logging
from typing import Any

from country_workspace.models import AsyncJob, Batch
from country_workspace.workspaces.admin.cleaners.validate import create_validation_jobs

logger = logging.getLogger(__name__)


def reprocess_batch(job: AsyncJob) -> dict[str, Any]:
    """
    Reprocess (re-validate) all records in a batch.

    This task re-runs validation on all households and individuals in a batch.
    It's useful when:
    - Validation rules have been updated in the program configuration
    - Data has been modified and needs to be revalidated
    - Initial validation encountered errors that have been fixed

    Records that have been pushed to HOPE Core (removed=True) are excluded
    from reprocessing as they should not be modified.

    Args:
        job: AsyncJob containing batch_id in config

    Returns:
        dict with processing statistics

    Raises:
        ValueError: if batch_id is not provided
        Batch.DoesNotExist: if batch is not found

    """
    batch_id = job.config.get("batch_id")
    if not batch_id:
        raise ValueError("batch_id is required in job config")

    batch = Batch.objects.select_related("program", "country_office").filter(pk=batch_id).first()
    if not batch:
        logger.error("Batch %s not found", batch_id)
        raise Batch.DoesNotExist(f"Batch {batch_id} not found")

    total_households = batch.household_set.count()
    total_individuals = batch.individual_set.filter(household=None).count()

    households_to_process = batch.household_set.filter(removed=False)
    individuals_to_process = batch.individual_set.filter(household=None, removed=False)

    household_count = households_to_process.count()
    individual_count = individuals_to_process.count()

    skipped_households = total_households - household_count
    skipped_individuals = total_individuals - individual_count
    if skipped_households > 0 or skipped_individuals > 0:
        logger.info(
            "Skipping %d household(s) and %d individual(s) already pushed to HOPE (removed=True) in batch %s",
            skipped_households,
            skipped_individuals,
            batch.name,
        )

    validation_jobs_created = 0

    if household_count > 0:
        queryset = households_to_process.prefetch_related("members")
        create_validation_jobs(
            description=f"Reprocess batch {batch.name} - Households",
            owner=job.owner,
            program=batch.program,
            queryset=queryset,
        )
        validation_jobs_created += 1

    # If batch has individuals without households, validate them
    if individual_count > 0:
        create_validation_jobs(
            description=f"Reprocess batch {batch.name} - Individuals",
            owner=job.owner,
            program=batch.program,
            queryset=individuals_to_process,
        )
        validation_jobs_created += 1

    result = {
        "batch_id": batch_id,
        "batch_name": batch.name,
        "households": household_count,
        "individuals": individual_count,
        "skipped_households": skipped_households,
        "skipped_individuals": skipped_individuals,
        "validation_jobs_created": validation_jobs_created,
    }

    logger.info("Batch reprocessing initiated: %s", result)
    return result
