from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0042_alter_transformer_value_transformations"),
    ]

    operations = [
        migrations.AddField(
            model_name="transformer",
            name="engine",
            field=models.CharField(
                choices=[("JAVASCRIPT", "JavaScript"), ("STEFICON", "Steficon Python")],
                default="JAVASCRIPT",
                help_text="Formula engine used to transform records.",
                max_length=20,
            ),
        ),
    ]
