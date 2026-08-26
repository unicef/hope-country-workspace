import contextlib
import logging
from datetime import timedelta
from typing import Any, Generator

import sentry_sdk
from celery.exceptions import Ignore
from constance import config as constance_config
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q, QuerySet
from django.db.models.fields.json import KeyTextTransform
from django.utils import timezone
from redis_lock import Lock

from country_workspace.cache.handlers import suppress_cache_updates
from country_workspace.cache.manager import cache_manager
from country_workspace.config.celery import app
from country_workspace.constants import HOUSEHOLD_ROLE_REF_FIELDS
from country_workspace.management.commands.sync import run_flex_fields_sync, run_geo_sync, run_program_sync
from country_workspace.models import AsyncJob, Batch, Rdp, Rdi, Household, Individual, Program
from country_workspace.models.jobs import GracefulJobCancellationError
from country_workspace.models.rdp import NON_TERMINAL_RDP_STATUSES

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
    affected_programs: set[int] = set()

    with suppress_cache_updates():
        while True:
            batch_h_pks = list(households_to_delete.order_by("pk").values_list("pk", flat=True)[:batch_size])
            if not batch_h_pks:
                break
            affected_programs.update(
                Batch.objects.filter(household__pk__in=batch_h_pks).values_list("program_id", flat=True).distinct()
            )
            _clear_heavy_fields(Individual.objects.filter(household_id__in=batch_h_pks))
            _clear_heavy_fields(Household.objects.filter(pk__in=batch_h_pks))
            _, counts = Household.objects.filter(pk__in=batch_h_pks).delete()
            deleted_h += counts.get("country_workspace.Household", 0)
            deleted_i += counts.get("country_workspace.Individual", 0)

        while True:
            batch_i_pks = list(individuals_to_delete.order_by("pk").values_list("pk", flat=True)[:batch_size])
            if not batch_i_pks:
                break
            affected_programs.update(
                Batch.objects.filter(individual__pk__in=batch_i_pks).values_list("program_id", flat=True).distinct()
            )
            _clear_heavy_fields(Individual.objects.filter(pk__in=batch_i_pks))
            _, counts = Individual.objects.filter(pk__in=batch_i_pks).delete()
            deleted_i += counts.get("country_workspace.Individual", 0)

    for program in Program.objects.filter(pk__in=affected_programs):
        cache_manager.incr_cache_version(program=program)

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


def _clear_heavy_fields(queryset: QuerySet) -> None:
    queryset.update(flex_fields={}, raw_data={}, flex_files=None)


@app.task()
def sync_hope_data() -> dict[str, dict[str, Any]]:
    """Periodic job that pulls reference data from HOPE.

    Runs the same routines exposed by the ``sync`` management command:

    * programs / offices / beneficiary groups (delta sync);
    * countries / area types / areas (delta sync);
    * HOPE flex field lookups (equivalent of the ``sync_flex_fields`` admin
      button).

    Programs and geo run in *delta* mode so each hourly tick only fetches
    records changed since the previous successful sync, keeping load on
    HOPE small. Errors in one block do not prevent the others from
    running; failures are logged and reported to Sentry instead of being
    re-raised, so a transient HOPE outage does not flood the worker with
    retries.

    Returns a per-block dict with the underlying sync stats so the result
    is inspectable from Flower / the Django admin. Successful entries look
    like::

        {
            "programs": {
                "status": "ok",
                "details": {
                    "offices": {"add": 1, "upd": 2, "errors": []},
                    ...
                },
            },
            "geo": {"status": "ok", "details": {...}},
            "flex_fields": {"status": "ok", "details": {"refreshed": 5}},
        }

    On failure the corresponding block carries ``{"status": "error",
    "error": "<message>"}`` instead of ``details``.
    """
    results: dict[str, dict[str, Any]] = {}
    runners = (
        ("programs", lambda: run_program_sync(delta_sync=True)),
        ("geo", lambda: run_geo_sync(delta_sync=True)),
        ("flex_fields", run_flex_fields_sync),
    )
    for label, runner in runners:
        try:
            details = runner()
        except Exception as exc:
            logger.exception("Periodic HOPE %s sync failed", label)
            sentry_sdk.capture_exception(exc)
            results[label] = {"status": "error", "error": str(exc)}
        else:
            results[label] = {"status": "ok", "details": details}
    return results


def _referenced_collector_reparenting(program_id: int, chunk: list) -> dict[int, int]:
    """Map collector PK -> a surviving batch id, for collectors still referenced outside this chunk.

    A household-less collector (`Individual.household is None`) is deduplicated program-wide
    (see `get_or_create_collector`) and can be referenced, via `primary_collector_id` /
    `alternate_collector_id` in `flex_fields`, by households belonging to batches other than
    the one that first created it. Those references are plain JSON values, not real FKs, so
    simply excluding the collector from the individuals about to be deleted is not enough: the
    `Batch` row it still points to is about to be deleted too, and `Individual.batch` is
    `on_delete=CASCADE`, which would take the collector down with it regardless. Reparenting the
    collector onto one of the still-referencing batches keeps it alive through that cascade.
    """
    fields = HOUSEHOLD_ROLE_REF_FIELDS
    rows = (
        Household.objects.filter(batch__program_id=program_id)
        .exclude(batch_id__in=chunk)
        .annotate(
            _primary=KeyTextTransform(fields.primary_collector, "flex_fields"),
            _alternate=KeyTextTransform(fields.alternate_collector, "flex_fields"),
        )
        .order_by("batch_id")
        .values_list("batch_id", "_primary", "_alternate")
    )
    reparenting: dict[int, int] = {}
    for batch_id, primary, alternate in rows.iterator():
        for value in (primary, alternate):
            if value:
                with contextlib.suppress(ValueError, TypeError):
                    reparenting.setdefault(int(value), batch_id)
    return reparenting


def _cleanup_batches(
    batch_ids: list, job: AsyncJob, program_id: int | None = None, batch_size: int = 5
) -> dict[str, int]:
    """Delete the given batches and their related households/individuals in chunks.

    Clears heavy fields before deletion to avoid loading large JSON payloads. Shared external
    collectors still referenced by households outside this cleanup (see
    `_referenced_collector_reparenting`) are reparented onto one of those surviving batches
    before anything is deleted, since a collector's owning batch is only the one that first
    created it, not every batch whose households later reuse it.
    Caller is responsible for `suppress_cache_updates()` wrapping and cache invalidation.
    """
    deleted_counts = {"batches": 0, "households": 0, "individuals": 0}

    for i in range(0, len(batch_ids), batch_size):
        job.ensure_not_cancelled(refresh=True)
        chunk = batch_ids[i : i + batch_size]

        if program_id:
            reparenting = _referenced_collector_reparenting(program_id, chunk)
            for collector_id, target_batch_id in reparenting.items():
                Individual.objects.filter(pk=collector_id, batch_id__in=chunk).update(batch_id=target_batch_id)

        individuals_queryset = Individual.objects.filter(batch_id__in=chunk)
        households_queryset = Household.objects.filter(batch_id__in=chunk)

        _clear_heavy_fields(individuals_queryset)
        _clear_heavy_fields(households_queryset)

        _, counts = individuals_queryset.delete()
        deleted_counts["individuals"] += counts.get("country_workspace.Individual", 0)

        _, counts = households_queryset.delete()
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
            deleted_counts.update(_cleanup_batches(batch_ids, job, program_id=program_id, batch_size=batch_size))

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
    if not (batch := job.batch):
        raise ValueError("batch is required for batch cleanup job")

    program = batch.program
    deleted_counts = {"batches": 0, "households": 0, "individuals": 0}

    with transaction.atomic(), suppress_cache_updates():
        Program.objects.select_for_update().get(pk=program.pk)
        if Rdp.objects.filter(
            Q(households__batch_id=batch.pk)
            | Q(households__members__batch_id=batch.pk)
            | Q(individuals__batch_id=batch.pk)
            | Q(individuals__household__batch_id=batch.pk),
            status__in=NON_TERMINAL_RDP_STATUSES,
        ).exists():
            raise ValueError("Cannot clean a batch referenced by an unfinished RDP.")

        deleted_counts.update(_cleanup_batches([batch.pk], job, program_id=program.pk))

    cache_manager.incr_cache_version(program=program)
    logger.info("Batch cleanup completed: %s", deleted_counts)
    return deleted_counts
