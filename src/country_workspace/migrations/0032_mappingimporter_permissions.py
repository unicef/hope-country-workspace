from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0031_update_mapping_importer_with_office"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="mappingimporter",
            options={
                "permissions": (
                    ("add_mappingimporter", "Can add Mapping Importer"),
                    ("change_mappingimporter", "Can change Mapping Importer"),
                    ("delete_mappingimporter", "Can delete Mapping Importer"),
                    ("view_mappingimporter", "Can view Mapping Importer"),
                ),
                "verbose_name": "Mapping Importer",
                "verbose_name_plural": "Mapping Importers",
            },
        ),
    ]
