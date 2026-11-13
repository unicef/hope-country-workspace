from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0074_update_rdp_job_action_paths"),
    ]

    operations = [
        migrations.AddField(
            model_name="program",
            name="biographic_deduplication_enabled",
            field=models.BooleanField(default=False, help_text="Is biographic deduplication enabled for this program?"),
        ),
        migrations.AddField(
            model_name="rdpoperation",
            name="external_id",
            field=models.CharField(
                blank=True,
                default="",
                editable=False,
                help_text="Identifier assigned by the external system that runs this operation, when it assigns one.",
                max_length=100,
            ),
        ),
    ]
