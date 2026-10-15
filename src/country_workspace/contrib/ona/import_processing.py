from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, NamedTuple, NotRequired

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone
from constance import config as constance_config
from country_workspace.contrib.ona.client import OnaClient
from country_workspace.contrib.ona.transformers import transform_submission_to_records
from country_workspace.constants import HOUSEHOLD_ROLE_REF_FIELDS
from country_workspace.models import AsyncJob, Batch, Household, Individual, Program, SyncLog
from country_workspace.notifications.signals import data_imported_signal
from country_workspace.models.household import (
    RELATIONSHIP_HEAD,
    RELATIONSHIP_NON_BENEFICIARY,
    ROLE_ALTERNATE,
    ROLE_PRIMARY,
)
from country_workspace.utils.config import BatchNameConfig, ValidateModeConfig
from country_workspace.utils.import_flow import (
    build_import_processor,
    get_or_create_collector,
    run_batch_postprocessing,
)
from country_workspace.workspaces.admin.cleaners.validate import create_validation_jobs

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from django.db.models import QuerySet


def get_ona_sync_log_name(form_id: str | int) -> str:
    return f"ona_{form_id}"


class Config(BatchNameConfig, ValidateModeConfig):
    form_id: str
    master_detail: bool
    household_mapping_id: NotRequired[int | None]
    individual_mapping_id: NotRequired[int | None]
    household_transformer_id: NotRequired[int | None]
    individual_transformer_id: NotRequired[int | None]
    household_field_mapping: NotRequired[dict[str, str]]
    individual_field_mapping: NotRequired[dict[str, str]]
    individuals_key: NotRequired[str]


class ImportResult(NamedTuple):
    people: int
    households: int = 0


class ImportedIndividual(NamedTuple):
    individual: Individual
    fields: dict[str, Any]


def import_data(job: AsyncJob) -> ImportResult:
    """
    INFORM/ONA RDI import entry point.

    Pulls submissions from ONA/INFORM, transforms them into Country Workspace
    household/individual records, then reuses the existing import processors,
    post-processing, and optional validation.

    This does not push anything to HOPE.
    """
    config: Config = job.config

    job.ensure_not_cancelled(refresh=True)

    if not config.get("form_id"):
        raise ImportError("form_id is required for ONA import")

    with transaction.atomic():
        batch_id = getattr(job, "batch_id", None)
        if batch_id:
            batch = (
                Batch.objects.select_for_update().select_related("program", "program__country_office").get(pk=batch_id)
            )
        else:
            batch = Batch.objects.create(
                name=config["batch_name"],
                program=job.program,
                country_office=job.program.country_office,
                imported_by=job.owner,
                source=Batch.BatchSource.ONA,
                status=Batch.BatchStatus.LOADING,
            )
            job.batch = batch
            job.save(update_fields=["batch"])

        if batch_id and batch.status != Batch.BatchStatus.LOADING:
            batch.status = Batch.BatchStatus.LOADING
            batch.save(update_fields=["status"])

    client = OnaClient(
        base_url=constance_config.ONA_API_URL,
        token=constance_config.ONA_API_TOKEN,
    )

    total_people = 0
    total_households = 0

    sync_log_name = get_ona_sync_log_name(config["form_id"])
    program_ct = ContentType.objects.get_for_model(Program)
    sync_log = SyncLog.objects.filter(name=sync_log_name, content_type=program_ct, object_id=job.program.id).first()
    last_id = int(sync_log.last_id) if sync_log and sync_log.last_id else None
    last_successful_id = last_id
    current_submission_id: int | None = None

    try:
        for submission in client.iter_submissions(config["form_id"], last_id=last_id):
            job.ensure_not_cancelled(refresh=True)

            current_submission_id = get_ona_submission_cursor_id(submission)
            if last_id is not None and current_submission_id <= last_id:
                continue

            imported = import_submission(
                batch=batch,
                submission=submission,
                config=config,
            )

            total_people += imported.people
            total_households += imported.households
            last_successful_id = current_submission_id

        job.ensure_not_cancelled(refresh=True)

        run_batch_postprocessing(
            batch,
            household_transformer_id=config.get("household_transformer_id"),
            individual_transformer_id=config.get("individual_transformer_id"),
        )

        job.ensure_not_cancelled(refresh=True)

        if config.get("validate_after_import"):
            create_validation_jobs(
                description=f"Validate records for batch {batch.pk}",
                owner=job.owner,
                program=job.program,
                queryset=_validation_queryset(batch, config),
                validation_scope="batch",
            )

        batch.status = Batch.BatchStatus.COMPLETE
        batch.save(update_fields=["status"])

        data_imported_signal.send(
            sender=Batch,
            program_id=batch.program_id,
            batch_id=batch.id,
            record_count=total_people + total_households,
            source=Batch.BatchSource.ONA,
        )

        return ImportResult(
            people=total_people,
            households=total_households,
        )

    except Exception:
        logger.exception(
            "INFORM/ONA import failed",
            extra={
                "batch_id": batch.pk,
                "form_id": config.get("form_id"),
                "submission_id": current_submission_id,
                "last_successful_submission_id": last_successful_id,
            },
        )
        raise
    finally:
        if last_successful_id and last_successful_id != last_id:
            SyncLog.objects.update_or_create(
                name=sync_log_name,
                content_type=program_ct,
                object_id=job.program.id,
                defaults={"last_id": str(last_successful_id), "last_update_date": timezone.now()},
            )


def import_submission(
    *,
    batch: Batch,
    submission: Mapping[str, Any],
    config: Config,
) -> ImportResult:
    originating_id = get_ona_originating_id(submission)

    transformed = transform_submission_to_records(
        submission,
        master_detail=config.get("master_detail", False),
        household_field_mapping=config.get("household_field_mapping", {}),
        individual_field_mapping=config.get("individual_field_mapping", {}),
        individuals_key=config.get("individuals_key", "individuals"),
    )

    with transaction.atomic():
        if config.get("master_detail"):
            household_record = transformed["household"] or {"fields": {}, "raw_data": {}}
            individual_records = transformed["individuals"]

            household = create_household(
                batch=batch,
                row=household_record["fields"],
                raw_data=household_record["raw_data"],
                config=config,
                originating_id=f"{originating_id}#HH0",
            )

            people_counter = 0
            imported_individuals: list[ImportedIndividual] = []
            for index, individual_record in enumerate(individual_records):
                imported_individual = create_individual(
                    batch=batch,
                    row=individual_record["fields"],
                    raw_data=individual_record["raw_data"],
                    config=config,
                    originating_id=f"{originating_id}#IND{index}",
                    household=household,
                )
                imported_individuals.append(imported_individual)
                people_counter += 1
            set_roles_and_relationships(household, imported_individuals)

            return ImportResult(
                people=people_counter,
                households=1,
            )

        people_counter = 0
        for index, individual_record in enumerate(transformed["individuals"]):
            create_individual(
                batch=batch,
                row=individual_record["fields"],
                raw_data=individual_record["raw_data"],
                config=config,
                originating_id=f"{originating_id}#IND{index}",
            )
            people_counter += 1

        return ImportResult(
            people=people_counter,
            households=0,
        )


def create_individual(  # noqa: PLR0913
    *,
    batch: Batch,
    row: Mapping[str, Any],
    raw_data: Mapping[str, Any],
    config: Config,
    originating_id: str,
    household: Household | None = None,
) -> ImportedIndividual:
    individual_row_processor = build_individual_processor(
        batch.program,
        mapping_id=config.get("individual_mapping_id"),
    )
    individual_fields = individual_row_processor(row)

    if individual_fields.get("relationship") == RELATIONSHIP_NON_BENEFICIARY:
        individual, _created = get_or_create_collector(
            program=batch.program,
            batch=batch,
            individual_fields=individual_fields,
            raw_data=dict(raw_data),
            originating_id=originating_id,
        )
    else:
        individual = Individual.objects.create(
            batch_id=batch.pk,
            name="",
            originating_id=originating_id,
            household=household,
            flex_fields=individual_fields,
            raw_data=dict(raw_data),
        )

    return ImportedIndividual(
        individual=individual,
        fields=individual_fields,
    )


def set_roles_and_relationships(
    household: Household,
    individuals: list[ImportedIndividual],
) -> None:
    fields = HOUSEHOLD_ROLE_REF_FIELDS

    primary_collector = next(
        (item.individual for item in individuals if item.fields.get("role") == ROLE_PRIMARY),
        None,
    )
    if primary_collector is not None:
        household.flex_fields[fields.primary_collector] = primary_collector.id

    alternate_collector = next(
        (item.individual for item in individuals if item.fields.get("role") == ROLE_ALTERNATE),
        None,
    )
    if alternate_collector is not None:
        household.flex_fields[fields.alternate_collector] = alternate_collector.id

    head_of_household = next(
        (item.individual for item in individuals if item.fields.get("relationship") == RELATIONSHIP_HEAD),
        None,
    )
    if head_of_household is not None:
        household.flex_fields[fields.head_of_household] = head_of_household.id

    household.save(update_fields=["flex_fields"])


def create_household(
    *,
    batch: Batch,
    row: Mapping[str, Any],
    raw_data: Mapping[str, Any],
    config: Config,
    originating_id: str,
) -> Household:
    household_row_processor = build_household_processor(
        batch.program,
        mapping_id=config.get("household_mapping_id"),
    )

    return Household.objects.create(
        batch_id=batch.pk,
        name="",
        originating_id=originating_id,
        flex_fields=household_row_processor(row),
        raw_data=dict(raw_data),
    )


def get_ona_submission_id(submission: Mapping[str, Any]) -> str:
    value = submission.get("_uuid") or submission.get("_id") or submission.get("id") or submission.get("uuid")

    if value is None:
        raise ImportError("ONA submission is missing _uuid/_id/id/uuid")

    return str(value)


def get_ona_submission_cursor_id(submission: Mapping[str, Any]) -> int:
    value = submission.get("_id") or submission.get("id")

    if value is None:
        raise ImportError("ONA submission is missing numeric _id/id required for resumable import cursor")

    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ImportError("ONA submission _id/id must be numeric for resumable import cursor") from exc


def get_ona_originating_id(submission: Mapping[str, Any]) -> str:
    return f"ONA#{get_ona_submission_id(submission)}"


def build_individual_processor(
    program: Program,
    mapping_id: int | None = None,
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    return build_import_processor(
        program=program,
        model=Individual,
        mapping_id=mapping_id,
        pre_processors=(),
        post_processors=(),
        source=Batch.BatchSource.ONA,
    )


def build_household_processor(
    program: Program,
    mapping_id: int | None = None,
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    return build_import_processor(
        program=program,
        model=Household,
        mapping_id=mapping_id,
        pre_processors=(),
        post_processors=(),
        source=Batch.BatchSource.ONA,
    )


def _validation_queryset(batch: Batch, config: Config) -> QuerySet[Household | Individual]:
    if config.get("master_detail"):
        return batch.household_set.filter(removed=False).prefetch_related("members")

    return batch.individual_set.filter(household__isnull=True, removed=False)
