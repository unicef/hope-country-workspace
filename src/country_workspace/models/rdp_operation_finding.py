from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import BaseModel


class RdpOperationFinding(BaseModel):
    """Represent a record-level finding produced by an RDP operation."""

    operation = models.ForeignKey(
        "RdpOperation",
        on_delete=models.CASCADE,
        related_name="findings",
        help_text=_("Operation that produced this finding."),
    )
    finding_type = models.CharField(
        max_length=50,
        help_text=_("Operation-specific finding type."),
    )
    individual = models.ForeignKey(
        "Individual",
        on_delete=models.CASCADE,
        related_name="rdp_operation_findings",
        help_text=_("Individual affected by this finding."),
    )
    field_name = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("Field affected by this finding, when applicable."),
    )
    related_individual = models.ForeignKey(
        "Individual",
        on_delete=models.CASCADE,
        related_name="+",
        null=True,
        blank=True,
        help_text=_("Related individual for findings involving another record."),
    )
    details = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Operation-specific finding details."),
    )
