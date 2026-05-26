from collections.abc import Mapping
from django.db import migrations, models
from django.db.migrations.state import StateApps
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def _remap_rdp_statuses(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor, mapping: Mapping[str, str]) -> None:
    Rdp = apps.get_model("country_workspace", "Rdp")
    db_alias = schema_editor.connection.alias
    for old, new in mapping.items():
        Rdp.objects.using(db_alias).filter(status=old).update(status=new)


def forward_rdp_statuses(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    _remap_rdp_statuses(
        apps,
        schema_editor,
        {
            "SUCCESS": "PUSHED",
            "CANCELLED": "REJECTED",
        },
    )


def backward_rdp_statuses(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    _remap_rdp_statuses(
        apps,
        schema_editor,
        {
            "PUSHED": "SUCCESS",
            "MERGED": "SUCCESS",
            "REJECTED": "CANCELLED",
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0054_rdp_deduplication_snapshots_and_more"),
    ]

    operations = [
        migrations.RunPython(forward_rdp_statuses, backward_rdp_statuses),
        migrations.AlterField(
            model_name="rdp",
            name="status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("PENDING", "Pending"),
                    ("FAILURE", "Failure"),
                    ("PUSHED", "Pushed"),
                    ("MERGED", "Merged"),
                    ("REJECTED", "Rejected"),
                ],
                default="PENDING",
                max_length=10,
            ),
        ),
    ]
