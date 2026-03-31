from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0052_rdp_parent"),
    ]

    operations = [
        migrations.RenameField(
            model_name="rdp",
            old_name="dedup_run_state",
            new_name="dedup_tracking_state",
        ),
        migrations.AlterField(
            model_name="rdp",
            name="dedup_tracking_state",
            field=models.CharField(
                max_length=15,
                choices=[
                    ("NOT_RUN", "Not run yet"),
                    ("IN_PROGRESS", "In progress"),
                    ("FINISHED", "Finished"),
                ],
                default="NOT_RUN",
                help_text="Local status used to decide whether DedupEngine should still be checked for this RDP.",
            ),
        ),
    ]
