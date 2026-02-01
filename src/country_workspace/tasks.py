import contextlib
import logging
from typing import Any, Generator

import sentry_sdk
from django.core.cache import cache
from django.db import transaction
from redis_lock import Lock

from country_workspace.config.celery import app
from country_workspace.models import AsyncJob, Batch, Rdp, Rdi

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
    deleted_counts = {"batches": 0, "households": 0, "individuals": 0, "rdps": 0, "rdis": 0, "jobs": 0}

    batch_ids = list(Batch.objects.filter(program_id=program_id).values_list("id", flat=True))
    if not batch_ids:
        return None

    for i in range(0, len(batch_ids), batch_size):
        chunk = batch_ids[i : i + batch_size]
        with transaction.atomic():
            _, counts = Batch.objects.filter(id__in=chunk).delete()
            deleted_counts["batches"] += counts.get("country_workspace.Batch", 0)
            deleted_counts["households"] += counts.get("country_workspace.Household", 0)
            deleted_counts["individuals"] += counts.get("country_workspace.Individual", 0)

    _, counts = Rdp.objects.filter(program_id=program_id).delete()
    deleted_counts["rdps"] = counts.get("country_workspace.Rdp", 0)

    _, counts = Rdi.objects.filter(program_id=program_id).delete()
    deleted_counts["rdis"] = counts.get("country_workspace.Rdi", 0)

    _, counts = AsyncJob.objects.filter(program_id=program_id).exclude(id=current_job_id).delete()
    deleted_counts["jobs"] = counts.get("country_workspace.AsyncJob", 0)

    return deleted_counts
