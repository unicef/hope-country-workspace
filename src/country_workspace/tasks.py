import contextlib
import logging
from typing import Any, Generator

import sentry_sdk
from celery.exceptions import Ignore
from django.core.cache import cache
from redis_lock import Lock

from country_workspace.cache.handlers import suppress_cache_updates
from country_workspace.cache.manager import cache_manager
from country_workspace.config.celery import app
from country_workspace.models import AsyncJob, Batch, Rdp, Rdi, Individual, Household
from country_workspace.models.jobs import GracefulJobCancellationError

logger = logging.getLogger(__name__)


@contextlib.contextmanager
def lock_job(job: AsyncJob) -> Generator[Lock, None, None]:
    lock = None
    if job.group_key:
        lock_key = f"lock:{job.group_key}"
        # Get a lock with a 60-second lifetime but keep renewing it automatically
        # to ensure the lock is held for as long as the Python process is running.
        lock = cache.lock(lock_key, 60, auto_renewal=True)
        yield lock.__enter__()
    else:
        yield
    if lock:
        lock.release()


@app.task(bind=True)
def sync_job_task(task: Any, pk: int, version: int) -> dict[str, Any]:
    try:
        job: AsyncJob = AsyncJob.objects.select_related("program", "program__country_office", "owner").get(
            pk=pk,
            version=version,
        )
    except AsyncJob.DoesNotExist as e:  # pragma: no cover
        sentry_sdk.capture_exception(e)
        raise

    with lock_job(job):
        try:
            scope = sentry_sdk.get_current_scope()
            job.ensure_not_cancelled(refresh=True)
            if job.program:
                sentry_sdk.set_tag("business_area", job.program.country_office.slug)
                sentry_sdk.set_tag("project", job.program.name)
            sentry_sdk.set_user({"id": job.owner.pk, "email": job.owner.email})
            return job.execute()
        except GracefulJobCancellationError as exc:
            logger.info("Task cancelled gracefully for AsyncJob #%s", job.pk)
            job.cancel()
            task.update_state(state="REVOKED", meta={"reason": str(exc), "job_id": job.pk})
            raise Ignore from exc
        finally:
            scope.clear()


@app.task()
def removed_expired_jobs(**kwargs: Any) -> None:
    AsyncJob.objects.filter(**kwargs).delete()


def _clear_heavy_fields(model: type, filter_kwargs: dict) -> None:
    model.objects.filter(**filter_kwargs).update(flex_fields={}, raw_data={}, flex_files=None)


def _cleanup_batches(batch_ids: list, job: AsyncJob, batch_size: int = 5) -> dict[str, int]:
    """Delete the given batches and their related households/individuals in chunks.

    Clears heavy fields before deletion to avoid loading large JSON payloads.
    Caller is responsible for `suppress_cache_updates()` wrapping and cache invalidation.
    """
    deleted_counts = {"batches": 0, "households": 0, "individuals": 0}

    for i in range(0, len(batch_ids), batch_size):
        job.ensure_not_cancelled(refresh=True)
        chunk = batch_ids[i : i + batch_size]

        _clear_heavy_fields(Individual, {"batch_id__in": chunk})
        _clear_heavy_fields(Household, {"batch_id__in": chunk})

        _, counts = Individual.objects.filter(batch_id__in=chunk).delete()
        deleted_counts["individuals"] += counts.get("country_workspace.Individual", 0)

        _, counts = Household.objects.filter(batch_id__in=chunk).delete()
        deleted_counts["households"] += counts.get("country_workspace.Household", 0)

        _, counts = Batch.objects.filter(id__in=chunk).delete()
        deleted_counts["batches"] += counts.get("country_workspace.Batch", 0)

    return deleted_counts


def clean_program_data(job: AsyncJob, batch_size: int = 5) -> dict | None:
    job.ensure_not_cancelled(refresh=True)
    program = job.program
    program_id = program.pk
    current_job_id = job.pk
    deleted_counts = {"batches": 0, "households": 0, "individuals": 0, "rdps": 0, "rdis": 0, "jobs": 0}

    batch_ids = list(Batch.objects.filter(program_id=program_id).values_list("id", flat=True))

    try:
        with suppress_cache_updates():
            deleted_counts.update(_cleanup_batches(batch_ids, job, batch_size=batch_size))

            job.ensure_not_cancelled(refresh=True)
            _, counts = Rdp.objects.filter(program_id=program_id).delete()
            deleted_counts["rdps"] = counts.get("country_workspace.Rdp", 0)

            job.ensure_not_cancelled(refresh=True)
            _, counts = Rdi.objects.filter(program_id=program_id).delete()
            deleted_counts["rdis"] = counts.get("country_workspace.Rdi", 0)

            job.ensure_not_cancelled(refresh=True)
            _, counts = AsyncJob.objects.filter(program_id=program_id).exclude(id=current_job_id).delete()
            deleted_counts["jobs"] = counts.get("country_workspace.AsyncJob", 0)
    finally:
        cache_manager.incr_cache_version(program=program)

    return deleted_counts


def batch_cleanup(job: AsyncJob) -> dict[str, int]:
    job.ensure_not_cancelled(refresh=True)
    batch = job.batch
    if not batch:
        raise ValueError("batch is required for batch cleanup job")

    program = batch.program
    deleted_counts = {"batches": 0, "households": 0, "individuals": 0}

    try:
        with suppress_cache_updates():
            deleted_counts.update(_cleanup_batches([batch.pk], job))
    finally:
        if program:
            cache_manager.incr_cache_version(program=program)

    logger.info("Batch cleanup completed: %s", deleted_counts)
    return deleted_counts
