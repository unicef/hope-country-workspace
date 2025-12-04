import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0032_program_system_fields"),
        ("hope_flex_fields", "0013_fielddefinition_validated_alter_datachecker_id_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="mappingimporter",
            name="office",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="mapping_importers",
                to="country_workspace.office",
                help_text="Business Area (Office) this mapping belongs to",
            ),
        ),
        # Change data_checker from OneToOneField to ForeignKey
        migrations.AlterField(
            model_name="mappingimporter",
            name="data_checker",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="mapping_importers",
                to="hope_flex_fields.datachecker",
                help_text="DataChecker (Household/Individual) this mapping is valid for",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="mappingimporter",
            unique_together={("office", "name")},
        ),
    ]
