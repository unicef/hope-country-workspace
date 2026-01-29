import contextlib
import logging
from typing import Any, Generator

import sentry_sdk
from django.core.cache import cache
from django.db import transaction
from redis_lock import Lock

from country_workspace.config.celery import app
from country_workspace.models import AsyncJob, Batch, Individual, Household, Rdp, Rdi

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


@app.task()
def sync_job_task(pk: int, version: int) -> dict[str, Any]:
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
            if job.program:
                sentry_sdk.set_tag("business_area", job.program.country_office.slug)
                sentry_sdk.set_tag("project", job.program.name)
            sentry_sdk.set_user({"id": job.owner.pk, "email": job.owner.email})
            return job.execute()
        finally:
            scope.clear()


@app.task()
def removed_expired_jobs(**kwargs: Any) -> None:
    AsyncJob.objects.filter(**kwargs).delete()


def clean_program_data(job: AsyncJob, batch_size: int = 1000) -> dict | None:
    program_id = job.program.pk
    current_job_id = job.pk
    deleted_counts = {"individuals": 0, "households": 0, "batches": 0, "rdps": 0, "rdis": 0, "jobs": 0}

    batch_ids = list(Batch.objects.filter(program_id=program_id).values_list("id", flat=True))
    if not batch_ids:
        return None

    while True:
        with transaction.atomic():
            individual_ids = list(
                Individual.objects.filter(batch_id__in=batch_ids).values_list("id", flat=True)[:batch_size]
            )

            if not individual_ids:
                break

            Individual.objects.filter(id__in=individual_ids).delete()
            deleted_counts["individuals"] += len(individual_ids)

    while True:
        with transaction.atomic():
            household_ids = list(
                Household.objects.filter(batch_id__in=batch_ids).values_list("id", flat=True)[:batch_size]
            )

            if not household_ids:
                break

            Household.objects.filter(id__in=household_ids).delete()
            deleted_counts["households"] += len(household_ids)

    with transaction.atomic():
        batch_count, _ = Batch.objects.filter(id__in=batch_ids).delete()
        deleted_counts["batches"] = batch_count

    with transaction.atomic():
        rdp_count, _ = Rdp.objects.filter(program_id=program_id).delete()
        deleted_counts["rdps"] = rdp_count

    with transaction.atomic():
        rdi_count, _ = Rdi.objects.filter(program_id=program_id).delete()
        deleted_counts["rdis"] = rdi_count

    with transaction.atomic():
        job_count, _ = AsyncJob.objects.filter(program_id=program_id).exclude(id=current_job_id).delete()
        deleted_counts["jobs"] = job_count

    return deleted_counts
