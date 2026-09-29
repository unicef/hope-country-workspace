import uuid

import concurrency.fields
import country_workspace.models.rdp_operation
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0063_alter_rdp_country_office_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="RdpOperation",
            fields=[
                ("last_modified", models.DateTimeField(auto_now=True)),
                ("version", concurrency.fields.IntegerVersionField(default=0, help_text="record revision number")),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        help_text="Unique identifier of this RDP operation and its external correlation ID.",
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "operation_type",
                    models.CharField(
                        choices=country_workspace.models.rdp_operation.get_rdp_operation_type_choices,
                        help_text="Type of operation to execute.",
                        max_length=50,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=country_workspace.models.rdp_operation.get_rdp_operation_status_choices,
                        default="PENDING",
                        help_text="Current execution status of this operation.",
                        max_length=20,
                    ),
                ),
                (
                    "config",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="Configuration captured when this operation was created.",
                    ),
                ),
                (
                    "error",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="Current execution error, if any.",
                    ),
                ),
                (
                    "log",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text="Chronological execution log for this operation.",
                    ),
                ),
                (
                    "attempt",
                    models.PositiveIntegerField(
                        default=0,
                        editable=False,
                        help_text="Number of execution attempts.",
                    ),
                ),
                (
                    "started_at",
                    models.DateTimeField(
                        editable=False,
                        help_text="Date and time when the current execution attempt started.",
                        null=True,
                    ),
                ),
                (
                    "finished_at",
                    models.DateTimeField(
                        editable=False,
                        help_text="Date and time when the current execution attempt finished.",
                        null=True,
                    ),
                ),
                (
                    "rdp",
                    models.ForeignKey(
                        help_text="RDP this operation belongs to.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="operations",
                        to="country_workspace.rdp",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="RdpOperationFinding",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("last_modified", models.DateTimeField(auto_now=True)),
                ("version", concurrency.fields.IntegerVersionField(default=0, help_text="record revision number")),
                (
                    "finding_type",
                    models.CharField(
                        help_text="Operation-specific finding type.",
                        max_length=50,
                    ),
                ),
                (
                    "field_name",
                    models.CharField(
                        blank=True,
                        help_text="Field affected by this finding, when applicable.",
                        max_length=255,
                    ),
                ),
                (
                    "details",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="Operation-specific finding details.",
                    ),
                ),
                (
                    "individual",
                    models.ForeignKey(
                        help_text="Individual affected by this finding.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="rdp_operation_findings",
                        to="country_workspace.individual",
                    ),
                ),
                (
                    "operation",
                    models.ForeignKey(
                        help_text="Operation that produced this finding.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="findings",
                        to="country_workspace.rdpoperation",
                    ),
                ),
                (
                    "related_individual",
                    models.ForeignKey(
                        blank=True,
                        help_text="Related individual for findings involving another record.",
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="related_rdp_operation_findings",
                        to="country_workspace.individual",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.AddConstraint(
            model_name="rdpoperation",
            constraint=models.UniqueConstraint(
                fields=("rdp", "operation_type"),
                name="uniq_rdp_operation_type",
                violation_error_message="An operation of this type already exists for this RDP.",
            ),
        ),
    ]
