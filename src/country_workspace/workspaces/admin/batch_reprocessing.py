import logging
from typing import Any

from country_workspace.models import AsyncJob, Batch, Household, MappingImporter, Individual, Transformer
from country_workspace.workspaces.admin.cleaners.validate import create_validation_jobs

logger = logging.getLogger(__name__)


def _apply_transformations(
    record: Household | Individual,
    mapping: MappingImporter | None = None,
    transformer: Transformer | None = None,
) -> bool:
    """Apply transformer first (keep fieldnames, transform values), then mapping (rename fields).

    Flow: row data => apply transformer => apply mapping => data checker (revalidate) => fields
    """
    if not record.raw_data:
        logger.warning("Record %s has no raw data, skipping transformations", record)
        return False

    data = record.raw_data.copy()

    if transformer:
        transformer.apply(data)

    if mapping:
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

    household_transformer_id = job.config.get("household_transformer_id")
    individual_transformer_id = job.config.get("individual_transformer_id")
    household_mapping_id = job.config.get("household_mapping_id")
    individual_mapping_id = job.config.get("individual_mapping_id")

    household_transformer = None
    individual_transformer = None
    household_mapping = None
    individual_mapping = None

    if household_transformer_id:
        try:
            household_transformer = Transformer.objects.get(pk=household_transformer_id)
            logger.info("Using household transformer: %s", household_transformer)
        except Transformer.DoesNotExist:
            logger.warning("Household transformer %s not found, skipping transformer", household_transformer_id)

    if individual_transformer_id:
        try:
            individual_transformer = Transformer.objects.get(pk=individual_transformer_id)
            logger.info("Using individual transformer: %s", individual_transformer)
        except Transformer.DoesNotExist:
            logger.warning("Individual transformer %s not found, skipping transformer", individual_transformer_id)

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

    # Apply transformations if provided (transformer first, then mapping)
    mapped_households = 0
    mapped_individuals = 0
    is_master_detail = batch.program.beneficiary_group and batch.program.beneficiary_group.master_detail

    if (household_transformer or household_mapping) and household_count > 0 and is_master_detail:
        logger.info(
            "Applying household transformations to %d households (transformer: %s, mapping: %s)",
            household_count,
            household_transformer.name if household_transformer else None,
            household_mapping.name if household_mapping else None,
        )
        for household in households_to_process:
            is_applied = _apply_transformations(household, household_mapping, household_transformer)
            mapped_households += int(is_applied)

        logger.info("Applied transformations to %d households", mapped_households)

    if (individual_transformer or individual_mapping) and individual_count > 0:
        logger.info(
            "Applying individual transformations to %d individuals (transformer: %s, mapping: %s)",
            individual_count,
            individual_transformer.name if individual_transformer else None,
            individual_mapping.name if individual_mapping else None,
        )
        for individual in individuals_to_process:
            is_applied = _apply_transformations(individual, individual_mapping, individual_transformer)
            mapped_individuals += int(is_applied)

        logger.info("Applied transformations to %d individuals", mapped_individuals)

    validation_jobs_created = 0
    if household_count > 0 and is_master_detail:
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

    if is_master_detail:
        response.update(
            {
                "households": household_count,
                "skipped_households": skipped_households,
                "mapped_households": mapped_households,
            }
        )

    logger.info("Batch reprocessing initiated: %s", response)
    return response
