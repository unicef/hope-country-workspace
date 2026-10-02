from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0065_migrate_legacy_rdp_deduplication"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="rdp",
            options={
                "permissions": [
                    ("cancel_rdp", "Can cancel RDP"),
                    ("create_rdp", "Can create RDP from selected beneficiaries"),
                    ("push_rdp_to_hope", "Can push RDP to HOPE"),
                    ("reset_rdp", "Can reset RDP"),
                ],
                "verbose_name": "Registration Data Push",
                "verbose_name_plural": "Registration Data Pushes",
            },
        ),
        migrations.RemoveConstraint(
            model_name="rdp",
            name="uniq_non_terminal_rdp_per_program",
        ),
        migrations.RemoveField(
            model_name="rdp",
            name="deduplication_set_id",
        ),
        migrations.RemoveField(
            model_name="rdp",
            name="is_dedup_settings_locked",
        ),
        migrations.AddConstraint(
            model_name="rdp",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status__in", ("PENDING", "FAILURE", "REVIEW_PENDING", "PUSH_PENDING"))),
                fields=("program",),
                name="uniq_non_terminal_rdp_per_program",
                violation_error_message="There is already an unfinished RDP for this program.",
            ),
        ),
        migrations.AlterConstraint(
            model_name="rdp",
            name="uniq_rdp_push_date_name",
            constraint=models.UniqueConstraint(
                fields=("push_date", "name"),
                name="uniq_rdp_push_date_name",
                violation_error_message="An RDP with this name and push date already exists.",
            ),
        ),
        migrations.AlterConstraint(
            model_name="rdp",
            name="rdp_push_attempt_state_consistent",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("push_attempt_id__isnull", False),
                        ("status", "PUSH_PENDING"),
                    ),
                    models.Q(
                        models.Q(("status", "PUSH_PENDING"), _negated=True),
                        ("push_attempt_id__isnull", True),
                    ),
                    _connector="OR",
                ),
                name="rdp_push_attempt_state_consistent",
                violation_error_message="Push attempt must be set only while the RDP push is in progress.",
            ),
        ),
    ]
