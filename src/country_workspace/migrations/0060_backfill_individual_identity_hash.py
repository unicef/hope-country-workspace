# Backfill identity_hash for existing external collectors (relationship == NON_BENEFICIARY).
# The hash logic below is a frozen copy of
# country_workspace.utils.import_flow.collector_identity — do not import it here,
# migrations must stay self-contained.

import hashlib
from typing import Any

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

COLLECTOR_HASH_FIELDS = (
    "given_name",
    "middle_name",
    "family_name",
    "full_name",
    "sex",
    "birth_date",
    "phone_no",
    "phone_no_alternative",
)


def _normalize(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()


def _compute_hash(flex_fields: dict) -> str | None:
    values = [_normalize(flex_fields.get(field)) for field in COLLECTOR_HASH_FIELDS]
    if not any(values):
        return None
    return hashlib.sha256(";".join(values).encode()).hexdigest()


def backfill_identity_hash(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    Individual = apps.get_model("country_workspace", "Individual")
    for individual in (
        Individual.objects.filter(flex_fields__relationship="NON_BENEFICIARY", identity_hash__isnull=True)
        .only("pk", "flex_fields")
        .iterator()
    ):
        identity_hash = _compute_hash(individual.flex_fields or {})
        if identity_hash:
            Individual.objects.filter(pk=individual.pk).update(identity_hash=identity_hash)


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0059_individual_identity_hash"),
    ]

    operations = [
        migrations.RunPython(backfill_identity_hash, migrations.RunPython.noop),
    ]
