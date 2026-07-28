# Generated for external collector program-wide deduplication

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0058_rdp_dedup_pending_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="individual",
            name="identity_hash",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text=(
                    "Identity hash used to deduplicate external collectors "
                    "(relationship == NON_BENEFICIARY) program-wide at import time."
                ),
                max_length=64,
                null=True,
            ),
        ),
    ]
