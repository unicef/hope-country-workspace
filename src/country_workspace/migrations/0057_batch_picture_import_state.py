from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0056_update_rdp_lifecycle"),
    ]

    operations = [
        migrations.AddField(
            model_name="batch",
            name="picture_import_state",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
