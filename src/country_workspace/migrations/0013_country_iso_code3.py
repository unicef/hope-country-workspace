from django.db import migrations, models
from django.db.migrations.state import StateApps
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def fill_iso_code3(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    Country = apps.get_model("country_workspace", "Country")
    for index, country in enumerate(Country.objects.all(), start=1):
        country.iso_code3 = f"{index:03d}"
        country.save()


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0012_country_hope_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="country",
            name="iso_code3",
            field=models.CharField(max_length=3, unique=True, null=True),
        ),
        migrations.RunPython(fill_iso_code3, reverse_code=migrations.RunPython.noop),
        migrations.AlterField(
            model_name="country",
            name="iso_code3",
            field=models.CharField(max_length=3, unique=True),
        ),
    ]
