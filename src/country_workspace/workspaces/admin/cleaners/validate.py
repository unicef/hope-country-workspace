import logging
from typing import Any
from itertools import batched
from collections.abc import Iterable

from concurrency.utils import fqn
from constance import config
from django.db.models import Model, QuerySet, Prefetch
from django.db.models.query import prefetch_related_objects

from country_workspace.context import batch_ctx
from country_workspace.models import AsyncJob, Household, Individual, Program
from country_workspace.state import state
from country_workspace.utils.imports import validate_alien_fields

logger = logging.getLogger(__name__)


def validate_queryset(queryset: QuerySet[Model], chunk_size: int = 2000, **kwargs: Any) -> dict[str, int]:
    valid = invalid = 0

    try:
        # Incluse forward FKs needed by the checker (no N+1 on program/country_office).
        queryset = queryset.select_related("batch__program", "batch__program__country_office")
        first = queryset.first()
        if not first:
            return {"valid": valid, "invalid": invalid}

        with state.set(tenant=first.country_office, program=first.program):
            if issubclass(queryset.model, Household):
                # Reverse-FK prefetch for Household.members; include forward FKs for Individuals
                prefetch_members = Prefetch(
                    "members",
                    queryset=Individual.objects.select_related("batch__program", "batch__program__country_office"),
                )
                # Stream DB rows in a stable PK order
                it = queryset.order_by("pk").iterator(chunk_size=chunk_size)
                # Batch objects to prefetch their reverse relations once per batch.
                for chunk in batched(it, chunk_size):
                    # Populate members for all objects in this batch (no N+1 on members access).
                    prefetch_related_objects(chunk, prefetch_members)
                    dv, di = _validate_and_count(chunk)
                    valid, invalid = valid + dv, invalid + di
            else:  # Individual
                # Just stream.
                dv, di = _validate_and_count(queryset.iterator(chunk_size=chunk_size))  # stream rows from DB
                valid, invalid = valid + dv, invalid + di

    except Exception as e:  # pragma: no cover
        logger.error("Error during queryset validation: %s", e)
        raise

    return {"valid": valid, "invalid": invalid}


def _validate_and_count(objs: Iterable[Model]) -> tuple[int, int]:
    valid = invalid = 0
    aliens_checked = False

    for obj in objs:
        if not aliens_checked:
            validate_alien_fields(obj)
            aliens_checked = True

        with batch_ctx(obj.batch_id):
            if obj.validate_with_checker():
                valid += 1
            else:
                invalid += 1

    return valid, invalid


def create_validation_jobs(description: str, owner: str, program: Program, queryset: QuerySet) -> AsyncJob:
    opts = queryset.model._meta
    queryset = queryset.order_by("pk").values_list("pk", flat=True)
    for chunk in batched(queryset, config.CHUNK_SIZE_FOR_VALIDATION_TASK):
        job = AsyncJob.objects.create(
            description=f"{description} (PKs {chunk[0]} - {chunk[-1]})",
            type=AsyncJob.JobType.ACTION,
            owner=owner,
            action=fqn(validate_queryset),
            program=program,
            config={"pks": chunk, "model_name": opts.label},
        )
        job.queue()
