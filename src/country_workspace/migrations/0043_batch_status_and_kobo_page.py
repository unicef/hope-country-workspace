from django.db import migrations, models
from django.db.migrations.state import StateApps
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def set_existing_batches_complete(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    Batch = apps.get_model("country_workspace", "Batch")
    Batch.objects.all().update(status="COMPLETE")


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0042_alter_transformer_value_transformations"),
    ]

    operations = [
        migrations.AddField(
            model_name="batch",
            name="status",
            field=models.CharField(
                choices=[("LOADING", "Loading"), ("COMPLETE", "Complete")],
                db_index=True,
                default="LOADING",
                max_length=32,
            ),
        ),
        migrations.RunPython(set_existing_batches_complete, migrations.RunPython.noop),
    ]
