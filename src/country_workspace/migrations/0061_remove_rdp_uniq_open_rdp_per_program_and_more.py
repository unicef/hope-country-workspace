from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0060_remove_individual_update_update_and_more"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="rdp",
            name="uniq_open_rdp_per_program",
        ),
        migrations.RemoveField(
            model_name="rdp",
            name="is_push_locked",
        ),
        migrations.AddField(
            model_name="rdp",
            name="push_attempt_id",
            field=models.UUIDField(
                editable=False,
                help_text="Unique identifier of the active HOPE push attempt. Cleared when the attempt finishes.",
                null=True,
            ),
        ),
        migrations.AddConstraint(
            model_name="rdp",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status__in", ("PENDING", "FAILURE", "DEDUP_PENDING", "PUSH_PENDING"))),
                fields=("program",),
                name="uniq_non_terminal_rdp_per_program",
                violation_error_message="There is already an unfinished RDP for this program.",
            ),
        ),
        migrations.AddConstraint(
            model_name="rdp",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("push_attempt_id__isnull", False), ("status", "PUSH_PENDING")),
                    models.Q(models.Q(("status", "PUSH_PENDING"), _negated=True), ("push_attempt_id__isnull", True)),
                    _connector="OR",
                ),
                name="rdp_push_attempt_state_consistent",
            ),
        ),
    ]
