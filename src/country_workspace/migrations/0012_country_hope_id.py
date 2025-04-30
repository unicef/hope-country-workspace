from django.db import migrations, models
from django.db.migrations.state import StateApps
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from uuid import uuid4


def fill_hope_id(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    Country = apps.get_model("country_workspace", "Country")
    for country in Country.objects.all():
        country.hope_id = f"TEMP_COUNTRY_{uuid4()}"
        country.save()


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0011_remove_household_updates_update_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="country",
            name="hope_id",
            field=models.CharField(editable=False, max_length=200, null=True, unique=True),
        ),
        migrations.RunPython(fill_hope_id, reverse_code=migrations.RunPython.noop),
        migrations.AlterField(
            model_name="country",
            name="hope_id",
            field=models.CharField(editable=False, max_length=200, unique=True),
        ),
    ]
