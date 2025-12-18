import logging
from typing import Any

from country_workspace.models import AsyncJob, Batch, MappingImporter
from country_workspace.workspaces.admin.cleaners.validate import create_validation_jobs

logger = logging.getLogger(__name__)


def reprocess_batch(job: AsyncJob) -> dict[str, Any]:  # noqa: C901, PLR0912, PLR0915
    batch_id = job.config.get("batch_id")
    if not batch_id:
        raise ValueError("batch_id is required in job config")

    batch = Batch.objects.select_related("program", "country_office").filter(pk=batch_id).first()
    if not batch:
        logger.error("Batch %s not found", batch_id)
        raise Batch.DoesNotExist(f"Batch {batch_id} not found")

    # Get optional mapping importers
    household_mapping_id = job.config.get("household_mapping_id")
    individual_mapping_id = job.config.get("individual_mapping_id")

    household_mapping = None
    individual_mapping = None

    if household_mapping_id:
        try:
            household_mapping = MappingImporter.objects.get(pk=household_mapping_id)
            logger.info("Using household mapping: %s", household_mapping)
        except MappingImporter.DoesNotExist:
            logger.warning("Household mapping %s not found, skipping mapping", household_mapping_id)

    if individual_mapping_id:
        try:
            individual_mapping = MappingImporter.objects.get(pk=individual_mapping_id)
            logger.info("Using individual mapping: %s", individual_mapping)
        except MappingImporter.DoesNotExist:
            logger.warning("Individual mapping %s not found, skipping mapping", individual_mapping_id)

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

    # Apply mappings if provided
    mapped_households = 0
    mapped_individuals = 0

    if household_mapping and household_count > 0:
        logger.info("Applying household mapping to %d households", household_count)
        for household in households_to_process:
            if household.raw_data:
                data = household.raw_data.copy()
                household_mapping.apply(data)
                household.flex_fields = data
                household.last_checked = None
                household.errors = {}
                household.save(update_fields=["flex_fields", "last_checked", "errors"])
                mapped_households += 1
        logger.info("Applied mapping to %d households", mapped_households)

    if individual_mapping and individual_count > 0:
        logger.info("Applying individual mapping to %d individuals", individual_count)
        for individual in individuals_to_process:
            if individual.raw_data:
                data = individual.raw_data.copy()
                individual_mapping.apply(data)
                individual.flex_fields = data
                individual.last_checked = None
                individual.errors = {}
                individual.save(update_fields=["flex_fields", "last_checked", "errors"])
                mapped_individuals += 1
        logger.info("Applied mapping to %d individuals", mapped_individuals)

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
        "mapped_households": mapped_households,
        "mapped_individuals": mapped_individuals,
        "validation_jobs_created": validation_jobs_created,
    }

    logger.info("Batch reprocessing initiated: %s", result)
    return result
