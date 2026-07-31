from typing import TYPE_CHECKING

from country_workspace.models import Batch, Individual, Transformer
from country_workspace.models.household import RELATIONSHIP_NON_BENEFICIARY

from .collector_identity import compute_collector_hash

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

        if transformed != current:
            record.flex_fields = transformed
            record.last_checked = None
            record.errors = {}
            update_fields = ["flex_fields", "last_checked", "errors"]
            if isinstance(record, Individual) and transformed.get("relationship") == RELATIONSHIP_NON_BENEFICIARY:
                # Keep the dedup key in sync with the stored identity fields,
                record.identity_hash = compute_collector_hash(transformed)
                update_fields.append("identity_hash")
            record.save(update_fields=tuple(update_fields))
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
