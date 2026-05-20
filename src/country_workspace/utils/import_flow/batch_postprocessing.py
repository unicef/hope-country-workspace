from collections.abc import Callable

from country_workspace.models import Batch
from .collector_linkage import sync_collector_links
from .transformations import apply_batch_transformers


type HouseholdRefsSyncer = Callable[[Batch], None]


def run_batch_postprocessing(
    batch: Batch,
    *,
    household_transformer_id: int | None = None,
    individual_transformer_id: int | None = None,
    sync_household_refs: HouseholdRefsSyncer | None = None,
) -> dict[str, int]:
    """Apply generated links and batch transformers after record import processing."""
    if sync_household_refs and batch.program.is_master_detail:
        sync_household_refs(batch)

    return {
        "collector_links": sync_collector_links(batch.individual_set.filter(removed=False)),
        **apply_batch_transformers(
            batch,
            household_transformer_id=household_transformer_id,
            individual_transformer_id=individual_transformer_id,
        ),
    }
