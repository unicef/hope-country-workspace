from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0057_batch_picture_import_state"),
    ]

    operations = [
        migrations.AlterField(
            model_name="rdp",
            name="status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("PENDING", "Pending"),
                    ("DEDUP_PENDING", "Awaiting deduplication"),
                    ("SUCCESS", "Success"),
                    ("FAILURE", "Failure"),
                    ("CANCELLED", "Cancelled"),
                ],
                default="PENDING",
                max_length=15,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="rdp",
            name="uniq_open_rdp_per_program",
        ),
        migrations.AddConstraint(
            model_name="rdp",
            constraint=models.UniqueConstraint(
                condition=models.Q(status__in=["PENDING", "FAILURE", "DEDUP_PENDING"]),
                fields=["program"],
                name="uniq_open_rdp_per_program",
                violation_error_message="There is already an active RDP for this program.",
            ),
        ),
    ]
