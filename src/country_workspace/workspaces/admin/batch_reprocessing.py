import logging
from typing import Any

from country_workspace.models import AsyncJob, Batch, Household, MappingImporter, Individual
from country_workspace.workspaces.admin.cleaners.validate import create_validation_jobs

logger = logging.getLogger(__name__)


def _apply_mapping(record: Household | Individual, mapping: MappingImporter) -> bool:
    if not record.raw_data:
        logger.warning("Record %s has no raw data, skipping mapping", record)
        return False

    data = record.raw_data.copy()
    mapping.apply(data)
    record.flex_fields = data
    record.last_checked = None
    record.errors = {}
    record.save(update_fields=["flex_fields", "last_checked", "errors"])
    return True


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
    total_individuals = batch.individual_set.count()

    households_to_process = batch.household_set.filter(removed=False)
    individuals_to_process = batch.individual_set.filter(removed=False)

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
            is_applied = _apply_mapping(household, household_mapping)
            mapped_households += int(is_applied)

        logger.info("Applied mapping to %d households", mapped_households)

    if individual_mapping and individual_count > 0:
        logger.info("Applying individual mapping to %d individuals", individual_count)
        for individual in individuals_to_process:
            is_applied = _apply_mapping(individual, individual_mapping)
            mapped_individuals += int(is_applied)

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

    if individual_count > 0:
        create_validation_jobs(
            description=f"Reprocess batch {batch.name} - Individuals",
            owner=job.owner,
            program=batch.program,
            queryset=individuals_to_process,
        )
        validation_jobs_created += 1

    response = {
        "batch_id": batch_id,
        "batch_name": batch.name,
        "individuals": individual_count,
        "skipped_individuals": skipped_individuals,
        "mapped_individuals": mapped_individuals,
        "validation_jobs_created": validation_jobs_created,
    }

    if batch.program and batch.program.beneficiary_group and batch.program.beneficiary_group.master_detail:
        response.update(
            {
                "households": household_count,
                "skipped_households": skipped_households,
                "mapped_households": mapped_households,
            }
        )

    logger.info("Batch reprocessing initiated: %s", response)
    return response
