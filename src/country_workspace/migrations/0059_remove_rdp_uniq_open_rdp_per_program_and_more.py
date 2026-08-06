from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps


def validate_rdp_push_attempt_state(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Validate existing RDP push states."""
    Rdp = apps.get_model("country_workspace", "Rdp")
    if invalid_ids := list(
        Rdp.objects.using(schema_editor.connection.alias)
        .exclude(
            models.Q(status="PUSH_PENDING", is_push_locked=True, push_attempt_id__isnull=False)
            | models.Q(~models.Q(status="PUSH_PENDING"), is_push_locked=False, push_attempt_id__isnull=True)
        )
        .values_list("pk", flat=True)[:10]
    ):
        raise RuntimeError(
            f"Cannot add the RDP push-state constraint: invalid push state found, including RDP IDs {invalid_ids}."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0058_rdp_dedup_pending_status"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="rdp",
            name="uniq_open_rdp_per_program",
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
        migrations.RunPython(validate_rdp_push_attempt_state, migrations.RunPython.noop),
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
                    models.Q(("is_push_locked", True), ("push_attempt_id__isnull", False), ("status", "PUSH_PENDING")),
                    models.Q(
                        models.Q(("status", "PUSH_PENDING"), _negated=True),
                        ("is_push_locked", False),
                        ("push_attempt_id__isnull", True),
                    ),
                    _connector="OR",
                ),
                name="rdp_push_attempt_state_consistent",
            ),
        ),
    ]
