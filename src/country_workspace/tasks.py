import contextlib
import logging
from datetime import timedelta
from typing import Any, Generator

import sentry_sdk
from celery.exceptions import Ignore
from constance import config as constance_config
from django.core.cache import cache
from django.utils import timezone
from redis_lock import Lock

from country_workspace.cache.handlers import suppress_cache_updates
from country_workspace.cache.manager import cache_manager
from country_workspace.config.celery import app
from country_workspace.models import AsyncJob, Batch, Rdp, Rdi, Household, Individual
from country_workspace.models.jobs import GracefulJobCancellationError

logger = logging.getLogger(__name__)


@app.task()
def cleanup_merged_rdp_data() -> None:
    days = constance_config.RDP_CLEANUP_DAYS
    if not days or days <= 0:
        return

    # Find successful RDPs older than threshold
    old_rdps = Rdp.objects.filter(status=Rdp.PushStatus.SUCCESS, push_date__lt=timezone.now() - timedelta(days=days))

    if not old_rdps.exists():
        return

    # Delete Households and Individuals associated with these RDPs,
    # but ONLY if they are not linked to any other RDP (pending, failed, or recent success).
    other_rdps = Rdp.objects.exclude(pk__in=old_rdps)

    households_to_delete = (
        Household.objects.filter(removed=True, rdp__in=old_rdps).exclude(rdp__in=other_rdps).distinct()
    )
    individuals_to_delete = (
        Individual.objects.filter(removed=True, rdp__in=old_rdps).exclude(rdp__in=other_rdps).distinct()
    )

    batch_size = constance_config.RDP_CLEANUP_BATCH_SIZE
    deleted_h = 0
    deleted_i = 0

    with suppress_cache_updates():
        # Process Households in batches. Deleting households also deletes their individuals via CASCADE.
        while True:
            batch_h_pks = list(households_to_delete.values_list("pk", flat=True)[:batch_size])
            if not batch_h_pks:
                break
            _, counts = Household.objects.filter(pk__in=batch_h_pks).delete()
            deleted_h += counts.get("country_workspace.Household", 0)
            deleted_i += counts.get("country_workspace.Individual", 0)

        # Process remaining Individuals in batches
        # those not linked to households or whose households were already deleted.
        while True:
            batch_i_pks = list(individuals_to_delete.values_list("pk", flat=True)[:batch_size])
            if not batch_i_pks:
                break
            _, counts = Individual.objects.filter(pk__in=batch_i_pks).delete()
            deleted_i += counts.get("country_workspace.Individual", 0)

    logger.info(
        "Deleted %s households and %s individuals from merged RDPs older than %s days",
        deleted_h,
        deleted_i,
        days,
    )


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
            task.update_state(
                state="REVOKED",
                meta={
                    "exc_type": type(exc).__name__,
                    "exc_module": type(exc).__module__,
                    "exc_message": str(exc),
                },
            )
            raise Ignore from exc
        finally:
            scope.clear()


@app.task()
def removed_expired_jobs(**kwargs: Any) -> None:
    AsyncJob.objects.filter(**kwargs).delete()


def _clear_heavy_fields(model: type, filter_kwargs: dict) -> None:
    model.objects.filter(**filter_kwargs).update(flex_fields={}, raw_data={}, flex_files=None)


def clean_program_data(job: AsyncJob, batch_size: int = 5) -> dict | None:
    job.ensure_not_cancelled(refresh=True)
    program = job.program
    program_id = program.pk
    current_job_id = job.pk
    deleted_counts = {"batches": 0, "households": 0, "individuals": 0, "rdps": 0, "rdis": 0, "jobs": 0}

    batch_ids = list(Batch.objects.filter(program_id=program_id).values_list("id", flat=True))

    try:
        with suppress_cache_updates():
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
