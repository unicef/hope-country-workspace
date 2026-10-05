from django.db import migrations
from django.db.migrations.state import StateApps
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


BIOMETRIC_DEDUPLICATION = "BIOMETRIC_DEDUPLICATION"
DEDUP_PENDING = "DEDUP_PENDING"
PENDING = "PENDING"
RUNNING = "RUNNING"
SUCCESS = "SUCCESS"
FAILURE = "FAILURE"


def migrate_legacy_deduplication(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    Rdp = apps.get_model("country_workspace", "Rdp")
    RdpOperation = apps.get_model("country_workspace", "RdpOperation")
    db_alias = schema_editor.connection.alias

    operations = []

    for rdp in (
        Rdp.objects.using(db_alias)
        .exclude(deduplication_set_id__isnull=True)
        .only("id", "deduplication_set_id", "status")
        .iterator()
    ):
        if rdp.status == DEDUP_PENDING:
            status = RUNNING
        elif rdp.status in {"PUSH_PENDING", "SUCCESS"}:
            status = SUCCESS
        else:
            status = FAILURE

        operations.append(
            RdpOperation(
                id=rdp.deduplication_set_id,
                rdp_id=rdp.pk,
                operation_type=BIOMETRIC_DEDUPLICATION,
                status=status,
            )
        )

    RdpOperation.objects.using(db_alias).bulk_create(operations)
    Rdp.objects.using(db_alias).filter(status=DEDUP_PENDING).update(status=PENDING)


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0064_create_rdp_operations"),
    ]

    operations = [
        migrations.RunPython(
            migrate_legacy_deduplication,
            migrations.RunPython.noop,
        ),
    ]
