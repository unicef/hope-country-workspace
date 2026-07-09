from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps
from django.db.models import Count
from django.utils import timezone


def cancel_duplicate_open_rdps(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Cancel older duplicate open RDPs before adding the open-RDP uniqueness constraint."""
    Rdp = apps.get_model("country_workspace", "Rdp")
    db_alias = schema_editor.connection.alias
    open_statuses = ["PENDING", "FAILURE"]

    duplicate_program_ids = (
        Rdp.objects.using(db_alias)
        .filter(status__in=open_statuses)
        .values("program_id")
        .annotate(count=Count("id"))
        .filter(count__gt=1)
        .values_list("program_id", flat=True)
    )

    timestamp = timezone.now().isoformat()
    for program_id in duplicate_program_ids:
        rdps = list(
            Rdp.objects.using(db_alias)
            .filter(program_id=program_id, status__in=open_statuses)
            .order_by("-push_date", "-pk")
        )

        for rdp in rdps[1:]:
            rdp.operation_log = [
                *(rdp.operation_log or []),
                {
                    "timestamp": timestamp,
                    "action": "CANCEL_RDP",
                    "result": {
                        "reason": "Auto-cancelled older duplicate open RDP before adding uniq_open_rdp_per_program.",
                    },
                },
            ]
            rdp.status = "CANCELLED"
            rdp.is_dedup_settings_locked = False
            rdp.save(update_fields=["status", "is_dedup_settings_locked", "operation_log"])


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0055_remove_rdp_parent"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="rdp",
            options={
                "permissions": [
                    ("cancel_rdp", "Can cancel RDP"),
                    ("create_rdp", "Can create RDP from selected beneficiaries"),
                    ("deduplicate_rdp", "Can run RDP deduplication"),
                    ("push_rdp_to_hope", "Can push RDP to HOPE"),
                    ("reset_rdp", "Can reset RDP"),
                ],
                "verbose_name": "Registration Data Push",
                "verbose_name_plural": "Registration Data Pushes",
            },
        ),
        migrations.RemoveField(
            model_name="rdp",
            name="deduplication_snapshots",
        ),
        migrations.AddField(
            model_name="rdp",
            name="is_push_locked",
            field=models.BooleanField(
                default=False,
                help_text="Locks this RDP while its push to HOPE is queued or running.",
            ),
        ),
        migrations.AddField(
            model_name="rdp",
            name="operation_log",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Append-only chronological log of RDP operations.",
            ),
        ),
        migrations.AlterField(
            model_name="rdp",
            name="is_dedup_settings_locked",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Locks program-level deduplication settings while this RDP deduplication is queued or running."
                ),
            ),
        ),
        migrations.RunPython(cancel_duplicate_open_rdps, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="rdp",
            name="uniq_pending_rdp_per_program",
        ),
        migrations.AddConstraint(
            model_name="rdp",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status__in", ["PENDING", "FAILURE"])),
                fields=("program",),
                name="uniq_open_rdp_per_program",
                violation_error_message="There is already an active RDP for this program.",
            ),
        ),
    ]
