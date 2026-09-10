from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import BaseModel


# Do not rename: migrations reference this callable by dotted path.
def get_rdp_operation_type_choices() -> list[tuple[str, str]]:
    return list(RdpOperation.Type.choices)


# Do not rename: migrations reference this callable by dotted path.
def get_rdp_operation_status_choices() -> list[tuple[str, str]]:
    return list(RdpOperation.Status.choices)


class RdpOperationType(models.TextChoices):
    DEDUPLICATION = "DEDUPLICATION", _("Deduplication")
    OCR = "OCR", _("OCR")


class RdpOperationStatus(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    IN_PROGRESS = "IN_PROGRESS", _("In progress")
    SUCCESS = "SUCCESS", _("Success")
    FAILURE = "FAILURE", _("Failure")


class RdpOperation(BaseModel):
    Type = RdpOperationType
    Status = RdpOperationStatus

    rdp = models.ForeignKey(
        "Rdp",
        on_delete=models.CASCADE,
        related_name="operations",
        help_text=_("RDP this operation belongs to."),
    )
    type = models.CharField(
        max_length=32,
        choices=get_rdp_operation_type_choices,
        help_text=_("Type of operation to perform for this RDP."),
    )
    status = models.CharField(
        max_length=16,
        choices=get_rdp_operation_status_choices,
        default=RdpOperationStatus.PENDING,
        help_text=_("Current execution status of the operation."),
    )
    attempt_id = models.UUIDField(
        null=True,
        editable=False,
        help_text=_("Unique identifier of the current or most recent execution attempt."),
    )
    external_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text=_("Identifier of the corresponding object in the external service, when applicable."),
    )
    operation_log = models.JSONField(
        default=list,
        blank=True,
        help_text=_("Append-only chronological log of this operation."),
    )
    started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("Date and time when the current or most recent execution attempt started."),
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("Date and time when the current or most recent execution attempt completed."),
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("rdp", "type"),
                name="uniq_rdp_operation_type",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_type_display()} for {self.rdp}"
