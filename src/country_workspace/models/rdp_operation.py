from uuid import uuid4

from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import BaseModel


class RdpOperationType(models.TextChoices):
    BIOMETRIC_DEDUPLICATION = "BIOMETRIC_DEDUPLICATION", _("Biometric deduplication")


class RdpOperationStatus(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    RUNNING = "RUNNING", _("Running")
    SUCCESS = "SUCCESS", _("Success")
    FAILURE = "FAILURE", _("Failure")


# Do not rename: migrations reference this callable by dotted path.
def get_rdp_operation_type_choices() -> list[tuple[str, str]]:
    return list(RdpOperationType.choices)


# Do not rename: migrations reference this callable by dotted path.
def get_rdp_operation_status_choices() -> list[tuple[str, str]]:
    return list(RdpOperationStatus.choices)


class RdpOperation(BaseModel):
    """Represent an operation executed for an RDP."""

    Type = RdpOperationType
    Status = RdpOperationStatus

    id = models.UUIDField(
        primary_key=True,
        default=uuid4,
        editable=False,
        help_text=_("Unique identifier of this RDP operation and its external correlation ID."),
    )
    rdp = models.ForeignKey(
        "Rdp",
        on_delete=models.CASCADE,
        related_name="operations",
        help_text=_("RDP this operation belongs to."),
    )
    operation_type = models.CharField(
        max_length=50,
        choices=get_rdp_operation_type_choices,
        help_text=_("Type of operation to execute."),
    )
    status = models.CharField(
        max_length=20,
        choices=get_rdp_operation_status_choices,
        default=Status.PENDING,
        help_text=_("Current execution status of this operation."),
    )
    config = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Configuration captured when this operation was created."),
    )
    error = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Current execution error, if any."),
    )
    log = models.JSONField(
        default=list,
        blank=True,
        help_text=_("Chronological execution log for this operation."),
    )
    attempt = models.PositiveIntegerField(
        default=0,
        editable=False,
        help_text=_("Number of execution attempts."),
    )
    started_at = models.DateTimeField(
        null=True,
        editable=False,
        help_text=_("Date and time when the current execution attempt started."),
    )
    finished_at = models.DateTimeField(
        null=True,
        editable=False,
        help_text=_("Date and time when the current execution attempt finished."),
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["rdp", "operation_type"],
                name="uniq_rdp_operation_type",
                violation_error_message=_("An operation of this type already exists for this RDP."),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.rdp} / {self.get_operation_type_display()}"
