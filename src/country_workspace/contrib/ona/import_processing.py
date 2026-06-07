from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any, NamedTuple, NotRequired

from django.db.models import QuerySet

from country_workspace.models import AsyncJob, Batch, Household, Individual, Program
from country_workspace.utils.config import BatchNameConfig, ValidateModeConfig
from country_workspace.utils.import_flow import build_import_processor, run_batch_postprocessing

logger = logging.getLogger(__name__)


class Config(BatchNameConfig, ValidateModeConfig):
    form_id: str
    token: str
    base_url: NotRequired[str]
    master_detail: bool
    household_mapping_id: NotRequired[int | None]
    individual_mapping_id: NotRequired[int | None]
    household_transformer_id: NotRequired[int | None]
    individual_transformer_id: NotRequired[int | None]


class ImportResult(NamedTuple):
    people: int
    households: int = 0


def import_data(job: AsyncJob) -> ImportResult:
    """
    INFORM/ONA RDI import entry point.

    This is intentionally a skeleton for now.
    It should eventually:
    1. Create a Batch with source INFORM/ONA
    2. Fetch ONA submissions
    3. Transform submissions into household/individual records
    4. Reuse build_import_processor()
    5. Run run_batch_postprocessing()
    6. Optionally trigger validation jobs

    It must NOT push anything to HOPE directly.
    """
    raise NotImplementedError("INFORM/ONA import is not wired yet.")


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