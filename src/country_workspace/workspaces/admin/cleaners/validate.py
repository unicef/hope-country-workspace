import logging
from typing import Any
from itertools import batched
from collections.abc import Iterable
from django.db.models import Model, QuerySet, Prefetch
from django.db.models.query import prefetch_related_objects

from country_workspace.context import batch_ctx
from country_workspace.models import AsyncJob, Household, Individual
from country_workspace.state import state


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


def validate_program(job: AsyncJob) -> dict[str, int]:
    try:
        program = job.program
        qs = program.households.all() if program.beneficiary_group.master_detail else program.individuals.all()
        return validate_queryset(qs)

    except Exception as e:  # pragma: no cover
        logger.error("Error during program validation: %s", e)
        raise


def _validate_and_count(objs: Iterable[Model]) -> tuple[int, int]:
    valid = invalid = 0
    for obj in objs:
        with batch_ctx(obj.batch_id):
            if obj.validate_with_checker():
                valid += 1
            else:
                invalid += 1
    return valid, invalid
