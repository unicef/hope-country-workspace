from collections import Counter
from typing import TYPE_CHECKING

from django.utils import timezone

if TYPE_CHECKING:
    from country_workspace.models import Batch, Household, Individual
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
    """Enforce identity_field uniqueness within *batch*.

    Cross-batch collision detection (matching records from different batches
    against the programme population) is handled by HOPE during the RDI merge
    step.  CW is only responsible for ensuring each batch pushed to HOPE
    contains no duplicate identity_field values.

    Records whose identity_field value appears more than once in the batch are
    marked with an ``errors["identity"]`` entry.  Records that were previously
    marked but no longer collide have their stale error cleared.
    """
    from country_workspace.models import Household, Individual

    program = batch.program

    if hh_field := get_identity_field_name(program.household_checker):
        _mark_batch_duplicates(Household, batch, hh_field)

    if ind_field := get_identity_field_name(program.individual_checker):
        _mark_batch_duplicates(Individual, batch, ind_field)


def _mark_batch_duplicates(
    model_class: type["Household | Individual"],
    batch: "Batch",
    field_name: str,
) -> None:
    """Mark records in *batch* that share an identity_field value with another record in the same batch."""
    records = list(
        model_class.objects.filter(batch=batch, removed=False)
        .exclude(**{f"flex_fields__{field_name}": None})
        .exclude(**{f"flex_fields__{field_name}": ""})
    )

    if not records:
        return

    values = [r.flex_fields[field_name] for r in records if r.flex_fields.get(field_name)]
    if not values:
        return

    duplicates: set[str] = {v for v, count in Counter(values).items() if count > 1}

    now = timezone.now()
    for record in records:
        value = record.flex_fields.get(field_name)
        if value in duplicates:
            msg = f"Duplicate '{field_name}' value '{value}' found within the same batch."
            if record.errors.get("identity") != msg:
                record.errors["identity"] = msg
                record.last_checked = now
                record.save(update_fields=["errors", "last_checked"])
        elif "identity" in record.errors:
            # Stale error — the duplicate was removed; clear it.
            record.errors.pop("identity")
            record.last_checked = now
            record.save(update_fields=["errors", "last_checked"])
