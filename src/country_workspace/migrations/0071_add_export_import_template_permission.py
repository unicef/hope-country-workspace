from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0070_flexfieldfile"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="program",
            options={
                "permissions": (
                    ("import_program_data", "Can Import beneficiaries"),
                    ("export_import_template", "Can Export import template"),
                ),
                "verbose_name": "Programme",
                "verbose_name_plural": "Programmes",
            },
        ),
    ]
