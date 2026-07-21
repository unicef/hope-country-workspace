from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any, NamedTuple, NotRequired

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from constance import config as constance_config
from country_workspace.contrib.ona.client import OnaClient
from country_workspace.contrib.ona.transformers import transform_submission_to_records
from country_workspace.models import AsyncJob, Batch, Household, Individual, Program, SyncLog
from country_workspace.utils.config import BatchNameConfig, ValidateModeConfig
from country_workspace.utils.import_flow import build_import_processor, run_batch_postprocessing
from country_workspace.workspaces.admin.cleaners.validate import create_validation_jobs

logger = logging.getLogger(__name__)


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
        for submission in client.iter_submissions(config["form_id"]):
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
            )

        batch.status = Batch.BatchStatus.COMPLETE
        batch.save(update_fields=["status"])

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
            household_data = transformed["household"] or {}
            individual_rows = transformed["individuals"]

            household = create_household(
                batch=batch,
                row=household_data,
                raw_submission=submission,
                config=config,
                originating_id=f"{originating_id}#HH0",
            )

            people_counter = 0
            for index, individual_data in enumerate(individual_rows):
                create_individual(
                    batch=batch,
                    row=individual_data,
                    raw_submission=submission,
                    config=config,
                    originating_id=f"{originating_id}#IND{index}",
                    household=household,
                )
                people_counter += 1

            return ImportResult(
                people=people_counter,
                households=1,
            )

        people_counter = 0
        for index, individual_data in enumerate(transformed["individuals"]):
            create_individual(
                batch=batch,
                row=individual_data,
                raw_submission=submission,
                config=config,
                originating_id=f"{originating_id}#IND{index}",
            )
            people_counter += 1

        return ImportResult(
            people=people_counter,
            households=0,
        )


def create_individual(
    *,
    batch: Batch,
    row: Mapping[str, Any],
    raw_submission: Mapping[str, Any],
    config: Config,
    originating_id: str,
    household: Household | None = None,
) -> Individual:
    individual_row_processor = build_individual_processor(
        batch.program,
        mapping_id=config.get("individual_mapping_id"),
    )

    return Individual.objects.create(
        batch_id=batch.pk,
        name="",
        originating_id=originating_id,
        household=household,
        flex_fields=individual_row_processor(row),
        raw_data={
            **dict(row),
            "_ona_source_submission": dict(raw_submission),
        },
    )


def create_household(
    *,
    batch: Batch,
    row: Mapping[str, Any],
    raw_submission: Mapping[str, Any],
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
        raw_data={
            **dict(row),
            "_ona_source_submission": dict(raw_submission),
        },
    )


def get_ona_submission_id(submission: Mapping[str, Any]) -> str:
    value = (
        submission.get("_uuid")
        or submission.get("_id")
        or submission.get("id")
        or submission.get("uuid")
    )

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