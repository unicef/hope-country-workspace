import country_workspace.validators.mapping
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0040_add_originating_id_to_validable"),
    ]

    operations = [
        migrations.AddField(
            model_name="mappingimporter",
            name="value_transformations",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Value transformation rules (one per line). Format: `fieldname:old_value=new_value`. Example: `sex:M=MALE` or `sex:F=FEMALE`. These transformations are applied after field name mapping.",
                validators=[country_workspace.validators.mapping.ValueTransformationRulesValidator()],
            ),
        ),
    ]
