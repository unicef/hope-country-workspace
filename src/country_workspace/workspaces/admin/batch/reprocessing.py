import logging
from collections.abc import Callable
from functools import partial
from typing import Any, Final, NamedTuple

from django.db.models import Count, F, Q, QuerySet, Value
from django.db.models.expressions import CombinedExpression
from django.db.models.fields.json import JSONField, KeyTextTransform, KeyTransform

from country_workspace.constants import HOUSEHOLD_ROLE_REF_FIELDS
from country_workspace.contrib.aurora.import_processing import (
    build_household_processor as build_aurora_household_processor,
    build_individual_processor as build_aurora_individual_processor,
)
from country_workspace.contrib.kobo.sync import (
    build_household_processor as build_kobo_household_processor,
    build_individual_processor as build_kobo_individual_processor,
)
from country_workspace.models import AsyncJob, Batch, Household, Individual, MappingImporter, Program
from country_workspace.utils.fields import to_reference_key
from country_workspace.utils.import_flow import run_batch_postprocessing, build_import_processor
from country_workspace.workspaces.admin.cleaners.validate import create_validation_jobs


logger = logging.getLogger(__name__)

PRESERVED_FLEX_FIELDS: Final[dict[str, dict[type[Household | Individual], tuple[str, ...]]]] = {
    Batch.BatchSource.KOBO: {
        Household: ("household_id",),
    },
}


class ResolvedReprocessConfig(NamedTuple):
    household_transformer_id: int | None
    individual_transformer_id: int | None
    household_mapping_id: int | None
    individual_mapping_id: int | None
    household_mapping: MappingImporter | None
    individual_mapping: MappingImporter | None


def _preserve_flex_fields(
    records: QuerySet[Household | Individual],
    batch: Batch,
    model: type[Household | Individual],
) -> tuple[QuerySet[Household | Individual], dict[str, str] | None]:
    if not (fields := PRESERVED_FLEX_FIELDS.get(batch.source, {}).get(model, ())):
        return records, None
    preserved = {field: f"_preserved_flex_field_{i}" for i, field in enumerate(fields)}
    return records.annotate(
        **{attr: KeyTransform(field, "flex_fields") for field, attr in preserved.items()}
    ), preserved


def _get_batch_from_job(job: AsyncJob) -> tuple[int, Batch]:
    batch_id = job.config.get("batch_id")
    if not batch_id:
        raise ValueError("batch_id is required in job config")

    batch = Batch.objects.select_related("program", "country_office").filter(pk=batch_id).first()
    if not batch:
        logger.error("Batch %s not found", batch_id)
        raise Batch.DoesNotExist(f"Batch {batch_id} not found")
    return batch_id, batch


def _sync_household_refs(batch: Batch) -> None:
    match batch.source:
        case Batch.BatchSource.KOBO:
            _sync_kobo_household_refs(batch)
        case Batch.BatchSource.RDI:
            _sync_rdi_household_refs(batch)


def _apply_import_processor(
    record: Household | Individual,
    processor: Callable[[Any], dict[str, Any]],
    preserved: dict[str, str] | None = None,
) -> bool:
    if not record.raw_data:
        logger.warning("Record %s has no raw data, skipping import processor", record)
        return False

    flex_fields = processor(record.raw_data)
    if preserved:
        flex_fields |= {
            field: value for field, attr in preserved.items() if (value := getattr(record, attr, None)) is not None
        }
    record.flex_fields = flex_fields
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
) -> Callable[[Any], dict[str, Any]]:
    if batch.source == Batch.BatchSource.KOBO:
        if model is Household:
            return build_kobo_household_processor(program, mapping_id)
        return build_kobo_individual_processor(program, mapping_id)

    if batch.source == Batch.BatchSource.AURORA:
        if model is Household:
            return build_aurora_household_processor(program, mapping_id)
        return build_aurora_individual_processor(program, mapping_id)

    return build_import_processor(
        program=program,
        model=model,
        mapping_id=mapping_id,
        source=batch.source,
    )


def _process_records(
    records: QuerySet[Household | Individual],
    processor: Callable[[Any], dict[str, Any]],
    preserved: dict[str, str] | None = None,
) -> int:
    return sum(int(_apply_import_processor(record, processor, preserved)) for record in records.iterator())


def _sync_rdi_household_refs(batch: Batch) -> None:
    individuals = (
        batch.individual_set.filter(removed=False)
        .annotate(_individual_id=KeyTextTransform("individual_id", "flex_fields"))
        .values_list("pk", "_individual_id")
    )
    pk_mapping = {ref: pk for pk, individual_id in individuals.iterator() if (ref := to_reference_key(individual_id))}

    fields = HOUSEHOLD_ROLE_REF_FIELDS
    households = (
        batch.household_set.filter(removed=False)
        .annotate(
            _hoh_ref=KeyTextTransform(fields.head_of_household, "flex_fields"),
            _primary_ref=KeyTextTransform(fields.primary_collector, "flex_fields"),
            _alternate_ref=KeyTextTransform(fields.alternate_collector, "flex_fields"),
        )
        .values_list("pk", "_hoh_ref", "_primary_ref", "_alternate_ref")
    )

    for pk, hoh_ref, primary_ref, alternate_ref in households.iterator():
        patch = {
            fields.head_of_household: pk_mapping.get(to_reference_key(hoh_ref)),
            fields.primary_collector: pk_mapping.get(to_reference_key(primary_ref)),
        }
        if alternate_ref := to_reference_key(alternate_ref):
            patch[fields.alternate_collector] = pk_mapping.get(alternate_ref)
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

    fields = HOUSEHOLD_ROLE_REF_FIELDS
    patches: dict[int, dict[str, int]] = {}

    for household_id, pk, role, relationship in members.iterator():
        patch = patches.setdefault(household_id, {})

        if role == "PRIMARY" and fields.primary_collector not in patch:
            patch[fields.primary_collector] = pk
        if role == "ALTERNATE" and fields.alternate_collector not in patch:
            patch[fields.alternate_collector] = pk
        if relationship == "HEAD" and fields.head_of_household not in patch:
            patch[fields.head_of_household] = pk

    for household_id, patch in patches.items():
        Household.objects.filter(pk=household_id).update(
            flex_fields=CombinedExpression(
                F("flex_fields"),
                "||",
                Value(patch, output_field=JSONField()),
            )
        )


def _resolve_config_object[T](
    queryset: QuerySet[T],
    object_id: int | None,
    label: str,
) -> tuple[int | None, T | None]:
    if object_id is None:
        return None, None
    if obj := queryset.filter(pk=object_id).first():
        logger.info("Using %s: %s", label.lower(), obj)
        return object_id, obj
    raise ValueError(f"{label} {object_id} is not available for this batch")


def _resolve_reprocess_config(batch: Batch, config: dict[str, Any]) -> ResolvedReprocessConfig:
    program = batch.program

    household_transformer_id, _ = _resolve_config_object(
        batch.country_office.transformers.all(),
        config.get("household_transformer_id"),
        "Household transformer",
    )
    individual_transformer_id, _ = _resolve_config_object(
        batch.country_office.transformers.all(),
        config.get("individual_transformer_id"),
        "Individual transformer",
    )

    household_mapping_id, household_mapping = (
        _resolve_config_object(
            MappingImporter.objects.filter(
                office=batch.country_office,
                data_checker=program.household_checker,
            ),
            config.get("household_mapping_id"),
            "Household mapping",
        )
        if program.is_master_detail and program.household_checker
        else (None, None)
    )

    individual_mapping_id, individual_mapping = (
        _resolve_config_object(
            MappingImporter.objects.filter(
                office=batch.country_office,
                data_checker=program.individual_checker,
            ),
            config.get("individual_mapping_id"),
            "Individual mapping",
        )
        if program.individual_checker
        else (None, None)
    )

    return ResolvedReprocessConfig(
        household_transformer_id=household_transformer_id,
        individual_transformer_id=individual_transformer_id,
        household_mapping_id=household_mapping_id,
        individual_mapping_id=individual_mapping_id,
        household_mapping=household_mapping,
        individual_mapping=individual_mapping,
    )


def _run_import_processors(  # noqa: PLR0913
    label: str,
    records: QuerySet[Household | Individual],
    count: int,
    mapping: MappingImporter | None,
    processor: Callable[[Any], dict[str, Any]],
    preserved: dict[str, str] | None = None,
) -> int:
    if count == 0:
        return 0
    logger.info(
        "Applying %s import processors to %d records (mapping: %s)",
        label,
        count,
        mapping.name if mapping else None,
    )
    processed = _process_records(records, processor, preserved)
    logger.info("Applied %s import processors to %d records", label, processed)
    return processed


def _active_records(
    records: QuerySet[Household | Individual],
) -> tuple[QuerySet[Household | Individual], int, int]:
    stats = records.aggregate(
        total=Count("pk"),
        active=Count("pk", filter=Q(removed=False)),
    )
    active = stats["active"] or 0
    total = stats["total"] or 0
    return records.filter(removed=False), active, total - active


def reprocess_batch(job: AsyncJob) -> dict[str, Any]:
    batch_id, batch = _get_batch_from_job(job)

    config = _resolve_reprocess_config(batch, job.config)
    is_master_detail = batch.program.is_master_detail

    households, household_count, skipped_households = (
        _active_records(batch.household_set.all()) if is_master_detail else (batch.household_set.none(), 0, 0)
    )
    individuals, individual_count, skipped_individuals = _active_records(batch.individual_set.all())
    if skipped_households or skipped_individuals:
        logger.info(
            "Skipping %d household(s) and %d individual(s) already pushed to HOPE (removed=True) in batch %s",
            skipped_households,
            skipped_individuals,
            batch.name,
        )

    build_processor = partial(_build_processor, batch=batch, program=batch.program)

    household_records, household_preserved = _preserve_flex_fields(
        households.only("pk", "name", "raw_data"),
        batch,
        Household,
    )
    processed_households = (
        _run_import_processors(
            label="household",
            records=household_records,
            count=household_count,
            mapping=config.household_mapping,
            processor=build_processor(model=Household, mapping_id=config.household_mapping_id),
            preserved=household_preserved,
        )
        if is_master_detail and household_count
        else 0
    )
    processed_individuals = (
        _run_import_processors(
            label="individual",
            records=individuals.only("pk", "name", "raw_data"),
            count=individual_count,
            mapping=config.individual_mapping,
            processor=build_processor(model=Individual, mapping_id=config.individual_mapping_id),
        )
        if individual_count
        else 0
    )

    run_batch_postprocessing(
        batch,
        household_transformer_id=config.household_transformer_id,
        individual_transformer_id=config.individual_transformer_id,
        sync_household_refs=_sync_household_refs,
    )

    if household_count > 0 and is_master_detail:
        create_validation_jobs(
            description=f"Validate records for batch {batch.pk}",
            owner=job.owner,
            program=batch.program,
            queryset=households.prefetch_related("members"),
        )
    elif individual_count > 0:
        create_validation_jobs(
            description=f"Validate records for batch {batch.pk}",
            owner=job.owner,
            program=batch.program,
            queryset=individuals,
        )

    response = {
        "batch_id": batch_id,
        "batch_name": batch.name,
        "individuals": individual_count,
        "skipped_individuals": skipped_individuals,
        "mapped_individuals": processed_individuals,
    }

    if is_master_detail:
        response.update(
            {
                "households": household_count,
                "skipped_households": skipped_households,
                "mapped_households": processed_households,
            }
        )

    logger.info("Batch reprocessing initiated: %s", response)
    return response


def apply_batch_transformers(job: AsyncJob) -> dict[str, Any]:
    batch_id, batch = _get_batch_from_job(job)

    household_transformer_id, _ = _resolve_config_object(
        batch.country_office.transformers.all(),
        job.config.get("household_transformer_id"),
        "Household transformer",
    )
    individual_transformer_id, _ = _resolve_config_object(
        batch.country_office.transformers.all(),
        job.config.get("individual_transformer_id"),
        "Individual transformer",
    )
    if not household_transformer_id and not individual_transformer_id:
        raise ValueError("At least one transformer id is required in job config")

    postprocessing_result = run_batch_postprocessing(
        batch,
        household_transformer_id=household_transformer_id,
        individual_transformer_id=individual_transformer_id,
        sync_household_refs=_sync_household_refs,
    )

    response = {
        "batch_id": batch_id,
        "batch_name": batch.name,
        "transformed_individuals": postprocessing_result.get("transformed_individuals", 0),
    }
    if batch.program.is_master_detail:
        response["transformed_households"] = postprocessing_result.get("transformed_households", 0)

    logger.info("Batch transformer apply finished: %s", response)
    return response
