import logging
from typing import Any

from country_workspace.cache.handlers import suppress_cache_updates
from country_workspace.cache.manager import cache_manager
from country_workspace.models import AsyncJob, Batch, Household, Individual

logger = logging.getLogger(__name__)


def _clear_heavy_fields(model: type, filter_kwargs: dict) -> None:
    model.objects.filter(**filter_kwargs).update(flex_fields={}, raw_data={}, flex_files=None)


def batch_cleanup(job: AsyncJob) -> dict[str, Any]:
    batch_ids = job.config.get("batch_ids")
    if not batch_ids:
        raise ValueError("batch_ids is required in job config")

    batches = Batch.objects.filter(pk__in=batch_ids).select_related("program")
    if not batches.exists():
        logger.warning("No batches found for IDs: %s", batch_ids)
        return {"batches": 0, "households": 0, "individuals": 0}

    program = batches.first().program
    deleted_counts = {"batches": 0, "households": 0, "individuals": 0}

    try:
        with suppress_cache_updates():
            for batch_id in batch_ids:
                job.ensure_not_cancelled(refresh=True)

                _clear_heavy_fields(Individual, {"batch_id": batch_id})
                _clear_heavy_fields(Household, {"batch_id": batch_id})

                _, counts = Individual.objects.filter(batch_id=batch_id).delete()
                deleted_counts["individuals"] += counts.get("country_workspace.Individual", 0)

                _, counts = Household.objects.filter(batch_id=batch_id).delete()
                deleted_counts["households"] += counts.get("country_workspace.Household", 0)

                _, counts = Batch.objects.filter(id=batch_id).delete()
                deleted_counts["batches"] += counts.get("country_workspace.Batch", 0)
    finally:
        cache_manager.incr_cache_version(program=program)

    logger.info("Batch cleanup completed: %s", deleted_counts)
    return deleted_counts
