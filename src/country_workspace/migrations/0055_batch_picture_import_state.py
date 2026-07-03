from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0054_rdp_deduplication_snapshots_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="batch",
            name="picture_import_state",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="batch",
            name="picture_import_state_updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="batch",
            name="picture_import_state_updated_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.SET_NULL,
                related_name="picture_import_state_batches",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
