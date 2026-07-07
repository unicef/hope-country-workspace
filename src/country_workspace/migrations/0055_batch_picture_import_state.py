from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0054_rdp_deduplication_snapshots_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="batch",
            name="picture_import_state",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
