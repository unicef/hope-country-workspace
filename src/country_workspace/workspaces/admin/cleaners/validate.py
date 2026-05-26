import logging
import math
import uuid
from typing import Any
from itertools import batched
from collections.abc import Iterable

from concurrency.utils import fqn
from constance import config
from django.core.cache import cache
from django.db.models import Model, QuerySet, Prefetch
from django.db.models.query import prefetch_related_objects

from country_workspace.context import batch_ctx
from country_workspace.models import AsyncJob, Household, Individual, Program
from country_workspace.state import state
from country_workspace.utils.imports import validate_alien_fields
from country_workspace.notifications.signals import validation_completed_signal

logger = logging.getLogger(__name__)
VALIDATION_PROGRESS_TTL_SECONDS = 24 * 60 * 60


def _emit_validation_completed(program_id: int, context: str, valid: int, invalid: int, sender: type[Model]) -> None:
    validation_completed_signal.send(
        sender=sender,
        program_id=program_id,
        context=context,
        results={"valid": valid, "invalid": invalid},
    )


def _aggregate_validation_result(  # noqa: PLR0913
    *,
    validation_run_id: str,
    total_chunks: int,
    program_id: int,
    context: str,
    valid: int,
    invalid: int,
    sender: type[Model],
) -> None:
    cache_key = f"validation-run:{validation_run_id}"
    progress: dict[str, int | str] = cache.get(cache_key, {})
    if not progress:
        progress = {
            "valid": 0,
            "invalid": 0,
            "completed_chunks": 0,
            "total_chunks": total_chunks,
            "program_id": program_id,
            "context": context,
        }

    progress["valid"] = int(progress.get("valid", 0)) + valid
    progress["invalid"] = int(progress.get("invalid", 0)) + invalid
    progress["completed_chunks"] = int(progress.get("completed_chunks", 0)) + 1
    cache.set(cache_key, progress, timeout=VALIDATION_PROGRESS_TTL_SECONDS)

    completed_chunks = int(progress["completed_chunks"])
    required_chunks = int(progress.get("total_chunks", total_chunks))
    if completed_chunks < required_chunks:
        return

    _emit_validation_completed(
        program_id=int(progress["program_id"]),
        context=str(progress["context"]),
        valid=int(progress["valid"]),
        invalid=int(progress["invalid"]),
        sender=sender,
    )
    cache.delete(cache_key)


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

            context = kwargs.get("context", "total")
            validation_run_id = kwargs.get("validation_run_id")
            total_chunks = kwargs.get("validation_total_chunks")

            if validation_run_id and total_chunks:
                _aggregate_validation_result(
                    validation_run_id=validation_run_id,
                    total_chunks=int(total_chunks),
                    program_id=first.program.id,
                    context=context,
                    valid=valid,
                    invalid=invalid,
                    sender=queryset.model,
                )
            else:
                _emit_validation_completed(
                    program_id=first.program.id,
                    context=context,
                    valid=valid,
                    invalid=invalid,
                    sender=queryset.model,
                )

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


def create_validation_jobs(
    description: str, owner: str, program: Program, queryset: QuerySet, *, context: str = "total"
) -> AsyncJob | None:
    opts = queryset.model._meta
    queryset = queryset.order_by("pk").values_list("pk", flat=True)
    chunk_size = config.CHUNK_SIZE_FOR_VALIDATION_TASK
    total_records = queryset.count()
    if total_records == 0:
        return None
    total_chunks = math.ceil(total_records / chunk_size)
    validation_run_id = uuid.uuid4().hex

    job: AsyncJob | None = None
    for chunk in batched(queryset, chunk_size):
        job = AsyncJob.objects.create(
            description=f"{description} (PKs {chunk[0]} - {chunk[-1]})",
            type=AsyncJob.JobType.ACTION,
            owner=owner,
            action=fqn(validate_queryset),
            program=program,
            config={
                "pks": chunk,
                "model_name": opts.label,
                "kwargs": {
                    "context": context,
                    "validation_run_id": validation_run_id,
                    "validation_total_chunks": total_chunks,
                },
            },
        )
        job.queue()
    return job
