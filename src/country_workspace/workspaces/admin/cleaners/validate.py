import logging
from typing import Any
from itertools import batched
from collections.abc import Iterable
from django.db.models import Model, QuerySet
from django.db.models.query import prefetch_related_objects

from country_workspace.context import batch_ctx
from country_workspace.models import AsyncJob, Household
from country_workspace.state import state


logger = logging.getLogger(__name__)


def validate_queryset(queryset: QuerySet[Model], chunk_size: int = 2000, **kwargs: Any) -> dict[str, int]:
    valid = invalid = 0

    try:
        first = queryset.first()
        if not first:
            return {"valid": valid, "invalid": invalid}

        with state.set(tenant=first.country_office, program=first.program):
            if queryset.model is Household:
                it = queryset.order_by("pk").iterator(chunk_size=chunk_size)
                for chunk in batched(it, chunk_size):
                    prefetch_related_objects(chunk, "members")
                    dv, di = _tally_validations(chunk)
                    valid, invalid = valid + dv, invalid + di
            else:  # Individual
                dv, di = _tally_validations(queryset.iterator(chunk_size=chunk_size))
                valid, invalid = valid + dv, invalid + di

    except Exception:  # pragma: no cover
        logger.exception("Error during queryset validation")
        raise

    return {"valid": valid, "invalid": invalid}


def validate_program(job: AsyncJob) -> dict[str, int]:
    try:
        program = job.program
        qs = program.households.all() if program.beneficiary_group.master_detail else program.individuals.all()
        return validate_queryset(qs)

    except Exception:  # pragma: no cover
        logger.exception("Error during program validation")
        raise


def _tally_validations(objs: Iterable[Model]) -> tuple[int, int]:
    valid = invalid = 0
    for obj in objs:
        with batch_ctx(obj.batch_id):
            if obj.validate_with_checker():
                valid += 1
            else:
                invalid += 1
    return valid, invalid
