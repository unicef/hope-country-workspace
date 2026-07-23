from typing import TYPE_CHECKING

from country_workspace.models import Batch, Individual, Transformer
from country_workspace.utils.import_flow.structural_fields import enforce_locked_fields

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from country_workspace.types import Beneficiary  # pyright: ignore[reportMissingModuleSource]


def _get_transformer(batch: Batch, transformer_id: int | None) -> Transformer | None:
    if not transformer_id:
        return None
    return batch.country_office.transformers.filter(pk=transformer_id).first()


def _apply_transformer(qs: "QuerySet[Beneficiary]", transformer: Transformer | None) -> int:
    if transformer is None:
        return 0

    count = 0
    for record in qs.only("pk", "flex_fields").iterator():
        current = record.flex_fields or {}
        transformed = transformer.apply(dict(current))

        if isinstance(record, Individual):
            # Transformers are for data cleanup: they must not rewrite structural
            # fields of external collectors (frozen, shared program-wide) nor turn
            # a member into a collector, or household/collector links would go stale.
            transformed = enforce_locked_fields(record, current, transformed)

        if transformed != current:
            updated = record.apply_flex_payload(transformed, preserve_existing_files=False)
            record.last_checked = None
            record.errors = {}
            record.save(update_fields=(*updated, "last_checked", "errors"))
            count += 1

    return count


def apply_batch_transformers(
    batch: Batch,
    *,
    household_transformer_id: int | None = None,
    individual_transformer_id: int | None = None,
) -> dict[str, int]:
    households = batch.household_set.filter(removed=False)
    individuals = batch.individual_set.filter(removed=False)

    return {
        "transformed_households": (
            _apply_transformer(households, _get_transformer(batch, household_transformer_id))
            if batch.program.is_master_detail
            else 0
        ),
        "transformed_individuals": _apply_transformer(
            individuals,
            _get_transformer(batch, individual_transformer_id),
        ),
    }
