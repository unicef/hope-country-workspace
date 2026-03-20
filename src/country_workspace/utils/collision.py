from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from django.utils import timezone

if TYPE_CHECKING:
    from country_workspace.models import Batch, Household, Individual, Program
    from hope_flex_fields.models import DataChecker


def get_identity_field_name(checker: "DataChecker | None") -> str | None:
    """Return the name of the IdentityField in *checker*, or ``None``.

    Iterates over all FlexFields exposed by the DataChecker and returns the
    name of the first one whose ``FieldDefinition.field_type`` is (or inherits
    from) ``IdentityField``.  The admin already enforces that at most one such
    field exists per DataChecker, so returning the first match is safe.
    """
    from hope_flex_fields.fields import IdentityField

    if not checker:
        return None

    for _fs, field in checker.get_fields():
        if issubclass(field.definition.field_type, IdentityField):
            return field.name
    return None


def detect_and_mark_collisions_for_batch(batch: "Batch") -> None:
    """Detect and mark identity collisions for all records in *batch*.

    Marks records whose IdentityField value collides with any other record
    in the same programme — either in a different batch (cross-batch) or
    within the same batch (within-batch duplicates).  Only records in the
    current batch are written to; pre-existing records in other batches are
    never modified.

    Stale identity errors on records that no longer collide are cleared.
    """
    from country_workspace.models import Household, Individual

    program = batch.program

    if hh_field := get_identity_field_name(program.household_checker):
        _mark_incoming_collisions(Household, program, batch, hh_field)

    if ind_field := get_identity_field_name(program.individual_checker):
        _mark_incoming_collisions(Individual, program, batch, ind_field)


def _mark_incoming_collisions(
    model_class: type["Household | Individual"],
    program: "Program",
    current_batch: "Batch",
    field_name: str,
) -> None:
    new_records = list(
        model_class.objects.filter(batch=current_batch, removed=False)
        .exclude(**{f"flex_fields__{field_name}": None})
        .exclude(**{f"flex_fields__{field_name}": ""})
    )

    if not new_records:
        return

    new_values = [r.flex_fields[field_name] for r in new_records if r.flex_fields.get(field_name)]
    if not new_values:
        return

    # Cross-batch: values that already exist in other batches of the same programme.
    cross_batch_values: set[str] = set(
        model_class.objects.filter(
            batch__program=program,
            removed=False,
            **{f"flex_fields__{field_name}__in": new_values},
        )
        .exclude(batch=current_batch)
        .values_list(f"flex_fields__{field_name}", flat=True)
    )

    # Within-batch: values that appear more than once in the current batch.
    within_batch_duplicates: set[str] = {v for v, count in Counter(new_values).items() if count > 1}

    colliding_values = cross_batch_values | within_batch_duplicates

    now = timezone.now()
    for record in new_records:
        value = record.flex_fields.get(field_name)
        if value in colliding_values:
            msg = f"Collision detected: '{field_name}' value '{value}' already exists in this programme."
            if record.errors.get("identity") != msg:
                record.errors["identity"] = msg
                record.last_checked = now
                record.save(update_fields=["errors", "last_checked"])
        # Clear any stale identity error for records that no longer collide.
        elif "identity" in record.errors:
            record.errors.pop("identity")
            record.last_checked = now
            record.save(update_fields=["errors", "last_checked"])
