from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import BaseModel


class RdpOperationUnitStatus(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    SUCCESS = "SUCCESS", _("Success")
    FAILURE = "FAILURE", _("Failure")


# Do not rename: migrations reference this callable by dotted path.
def get_rdp_operation_unit_status_choices() -> list[tuple[str, str]]:
    return list(RdpOperationUnitStatus.choices)


class RdpOperationUnit(BaseModel):
    """Represent one persistent unit of work within an RDP operation."""

    Status = RdpOperationUnitStatus

    operation = models.ForeignKey(
        "RdpOperation",
        on_delete=models.CASCADE,
        related_name="units",
        help_text=_("RDP operation this unit belongs to."),
    )
    individual = models.ForeignKey(
        "Individual",
        on_delete=models.CASCADE,
        related_name="rdp_operation_units",
        help_text=_("Individual processed by this operation unit."),
    )
    status = models.CharField(
        max_length=20,
        choices=get_rdp_operation_unit_status_choices,
        default=Status.PENDING,
        help_text=_("Current processing status of this unit."),
    )
    config = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Operation-specific configuration for this unit."),
    )
    error = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Current processing error, if any."),
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["operation", "individual"],
                name="uniq_rdp_operation_unit_individual",
                violation_error_message=_("An operation unit for this individual already exists."),
            ),
        ]
