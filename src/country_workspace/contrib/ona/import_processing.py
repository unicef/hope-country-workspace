from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any, NamedTuple, NotRequired

from django.db import transaction
from django.db.models import QuerySet

from country_workspace.contrib.ona.client import OnaClient
from country_workspace.contrib.ona.transformers import transform_submission_to_records
from country_workspace.models import AsyncJob, Batch, Household, Individual, Program
from country_workspace.utils.config import BatchNameConfig, ValidateModeConfig
from country_workspace.utils.import_flow import build_import_processor, run_batch_postprocessing
from country_workspace.workspaces.admin.cleaners.validate import create_validation_jobs

logger = logging.getLogger(__name__)

DEFAULT_ONA_BASE_URL = "https://api.ona.io"


class Config(BatchNameConfig, ValidateModeConfig):
    form_id: str
    token: str
    base_url: NotRequired[str]
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

    if not config.get("token"):
        raise ImportError("token is required for ONA import")

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
        base_url=config.get("base_url", DEFAULT_ONA_BASE_URL),
        token=config["token"],
    )

    total_people = 0
    total_households = 0

    try:
        for submission in client.iter_submissions(config["form_id"]):
            job.ensure_not_cancelled(refresh=True)

            imported = import_submission(
                batch=batch,
                submission=submission,
                config=config,
            )

            total_people += imported.people
            total_households += imported.households

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
            },
        )
        raise


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
            "fields": dict(row),
            "source_submission": dict(raw_submission),
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
            "fields": dict(row),
            "source_submission": dict(raw_submission),
        },
    )


def get_ona_originating_id(submission: Mapping[str, Any]) -> str:
    value = (
        submission.get("_uuid")
        or submission.get("_id")
        or submission.get("id")
        or submission.get("uuid")
    )

    if value is None:
        raise ImportError("ONA submission is missing _uuid/_id/id/uuid")

    return f"ONA#{value}"


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