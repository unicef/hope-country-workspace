import logging
from collections.abc import Callable
from typing import Any

from django.db.models import F, Value
from django.db.models.expressions import CombinedExpression
from django.db.models.fields.json import JSONField, KeyTextTransform

from country_workspace.contrib.aurora.import_processing import (
    build_household_transform as build_aurora_household_processor,
    build_individual_transform as build_aurora_individual_processor,
)
from country_workspace.contrib.kobo.sync import (
    build_household_processor as build_kobo_household_processor,
    build_individual_processor as build_kobo_individual_processor,
)
from country_workspace.models import AsyncJob, Batch, Household, Individual, MappingImporter, Program, Transformer
from country_workspace.utils.collector_linkage import sync_collector_links
from country_workspace.utils.import_processing import build_import_processor
from country_workspace.workspaces.admin.cleaners.validate import create_validation_jobs


logger = logging.getLogger(__name__)


def _apply_transformations(
    record: Household | Individual,
    processor: Callable[[Any], dict[str, Any]],
) -> bool:
    if not record.raw_data:
        logger.warning("Record %s has no raw data, skipping transformations", record)
        return False

    data = processor(record.raw_data)

    record.flex_fields = data
    record.last_checked = None
    record.errors = {}
    record.save(update_fields=["flex_fields", "last_checked", "errors"])
    return True


def _build_processor(
    *,
    batch: Batch,
    program: Program,
    model: type[Household] | type[Individual],
    mapping_id: int | None,
    transformer_id: int | None,
) -> Callable[[Any], dict[str, Any]]:
    if batch.source == Batch.BatchSource.KOBO:
        if model is Household:
            return build_kobo_household_processor(program, mapping_id, transformer_id)
        return build_kobo_individual_processor(program, mapping_id, transformer_id)

    if batch.source == Batch.BatchSource.AURORA:
        if model is Household:
            return build_aurora_household_processor(program, mapping_id, transformer_id)
        return build_aurora_individual_processor(program, mapping_id, transformer_id)

    return build_import_processor(
        program=program,
        model=model,
        mapping_id=mapping_id,
        transformer_id=transformer_id,
        source=batch.source,
    )


def _sync_rdi_household_refs(batch: Batch) -> None:
    individuals = (
        batch.individual_set.filter(removed=False)
        .annotate(_individual_id=KeyTextTransform("individual_id", "flex_fields"))
        .values_list("pk", "_individual_id")
    )
    pk_mapping = {individual_id: pk for pk, individual_id in individuals.iterator()}

    households = (
        batch.household_set.filter(removed=False)
        .annotate(
            _head_of_household_id=KeyTextTransform("head_of_household_id", "flex_fields"),
            _head_of_household=KeyTextTransform("head_of_household", "flex_fields"),
            _primary_collector_id=KeyTextTransform("primary_collector_id", "flex_fields"),
            _primary_collector=KeyTextTransform("primary_collector", "flex_fields"),
            _alternate_collector_id=KeyTextTransform("alternate_collector_id", "flex_fields"),
            _alternate_collector=KeyTextTransform("alternate_collector", "flex_fields"),
        )
        .values_list(
            "pk",
            "_head_of_household_id",
            "_head_of_household",
            "_primary_collector_id",
            "_primary_collector",
            "_alternate_collector_id",
            "_alternate_collector",
        )
    )

    for pk, hoh_id, hoh, primary_id, primary, alt_id, alt in households.iterator():
        patch = {
            "head_of_household_id": pk_mapping.get(hoh_id or hoh),
            "primary_collector_id": pk_mapping.get(primary_id or primary),
        }

        if alt_ref := alt_id or alt:
            patch["alternate_collector_id"] = pk_mapping.get(alt_ref)

        Household.objects.filter(pk=pk).update(
            flex_fields=CombinedExpression(
                F("flex_fields"),
                "||",
                Value(patch, output_field=JSONField()),
            )
        )


def _sync_kobo_household_refs(batch: Batch) -> None:
    members = (
        batch.individual_set.filter(
            removed=False,
            household__removed=False,
            household_id__isnull=False,
        )
        .annotate(
            _role=KeyTextTransform("role", "flex_fields"),
            _relationship=KeyTextTransform("relationship", "flex_fields"),
        )
        .values_list("household_id", "pk", "_role", "_relationship")
        .order_by("household_id", "pk")
    )

    patches: dict[int, dict[str, int]] = {}

    for household_id, pk, role, relationship in members.iterator():
        patch = patches.setdefault(household_id, {})

        if role == "PRIMARY" and "primary_collector_id" not in patch:
            patch["primary_collector_id"] = pk
        if role == "ALTERNATE" and "alternate_collector_id" not in patch:
            patch["alternate_collector_id"] = pk
        if relationship == "HEAD" and "head_of_household_id" not in patch:
            patch["head_of_household_id"] = pk

    for household_id, patch in patches.items():
        Household.objects.filter(pk=household_id).update(
            flex_fields=CombinedExpression(
                F("flex_fields"),
                "||",
                Value(patch, output_field=JSONField()),
            )
        )


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
            household_transformer_id = None

    if individual_transformer_id:
        try:
            individual_transformer = Transformer.objects.get(pk=individual_transformer_id)
            logger.info("Using individual transformer: %s", individual_transformer)
        except Transformer.DoesNotExist:
            logger.warning("Individual transformer %s not found, skipping transformer", individual_transformer_id)
            individual_transformer_id = None

    if household_mapping_id:
        try:
            household_mapping = MappingImporter.objects.get(pk=household_mapping_id)
            logger.info("Using household mapping: %s", household_mapping)
        except MappingImporter.DoesNotExist:
            logger.warning("Household mapping %s not found, skipping mapping", household_mapping_id)
            household_mapping_id = None

    if individual_mapping_id:
        try:
            individual_mapping = MappingImporter.objects.get(pk=individual_mapping_id)
            logger.info("Using individual mapping: %s", individual_mapping)
        except MappingImporter.DoesNotExist:
            logger.warning("Individual mapping %s not found, skipping mapping", individual_mapping_id)
            individual_mapping_id = None

    total_households = batch.household_set.count()
    total_individuals = batch.individual_set.count()

    households_to_process = batch.household_set.filter(removed=False).only("pk", "name", "raw_data")
    individuals_to_process = batch.individual_set.filter(removed=False).only("pk", "name", "raw_data")

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

    mapped_households = 0
    mapped_individuals = 0
    is_master_detail = batch.program.is_master_detail

    household_processor = _build_processor(
        batch=batch,
        program=batch.program,
        model=Household,
        mapping_id=household_mapping_id,
        transformer_id=household_transformer_id,
    )
    individual_processor = _build_processor(
        batch=batch,
        program=batch.program,
        model=Individual,
        mapping_id=individual_mapping_id,
        transformer_id=individual_transformer_id,
    )

    if household_count > 0 and is_master_detail:
        logger.info(
            "Applying household transformations to %d households (transformer: %s, mapping: %s)",
            household_count,
            household_transformer.name if household_transformer else None,
            household_mapping.name if household_mapping else None,
        )
        for household in households_to_process.iterator():
            is_applied = _apply_transformations(household, household_processor)
            mapped_households += int(is_applied)

        logger.info("Applied transformations to %d households", mapped_households)

    if individual_count > 0:
        logger.info(
            "Applying individual transformations to %d individuals (transformer: %s, mapping: %s)",
            individual_count,
            individual_transformer.name if individual_transformer else None,
            individual_mapping.name if individual_mapping else None,
        )
        for individual in individuals_to_process.iterator():
            is_applied = _apply_transformations(individual, individual_processor)
            mapped_individuals += int(is_applied)

        logger.info("Applied transformations to %d individuals", mapped_individuals)

    if is_master_detail:
        match batch.source:
            case Batch.BatchSource.KOBO:
                _sync_kobo_household_refs(batch)
            case Batch.BatchSource.RDI:
                _sync_rdi_household_refs(batch)
    sync_collector_links(individuals_to_process)

    if household_count > 0 and is_master_detail:
        create_validation_jobs(
            description=f"Validate records for batch {batch.pk}",
            owner=job.owner,
            program=batch.program,
            queryset=households_to_process.prefetch_related("members"),
        )
    elif individual_count > 0:
        create_validation_jobs(
            description=f"Validate records for batch {batch.pk}",
            owner=job.owner,
            program=batch.program,
            queryset=individuals_to_process,
        )

    response = {
        "batch_id": batch_id,
        "batch_name": batch.name,
        "individuals": individual_count,
        "skipped_individuals": skipped_individuals,
        "mapped_individuals": mapped_individuals,
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
