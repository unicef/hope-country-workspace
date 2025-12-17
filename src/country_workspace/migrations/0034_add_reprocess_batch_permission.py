from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0033_update_mapping_importer_with_office"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="batch",
            options={
                "verbose_name": "Batch",
                "verbose_name_plural": "Batches",
                "permissions": (("reprocess_batch", "Can reprocess batch"),),
            },
        ),
    ]
