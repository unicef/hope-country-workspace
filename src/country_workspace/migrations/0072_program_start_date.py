from django.db import migrations, models
from django.db.migrations.state import StateApps
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def reset_blob_hashes(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    for model_name in ("Household", "Individual"):
        apps.get_model("country_workspace", model_name).objects.exclude(blob_hashes={}).update(blob_hashes={})


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0071_add_export_import_template_permission"),
    ]

    operations = [
        migrations.AddField(
            model_name="program",
            name="start_date",
            field=models.DateField(blank=True, editable=False, null=True),
        ),
        migrations.RunPython(reset_blob_hashes, migrations.RunPython.noop),
    ]
