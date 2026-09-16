from uuid import uuid4

from django.db import models
from django.utils.translation import gettext as _


class OcrRun(models.Model):
    """Tracks a single OCR run for an RDP.

    v1 allows exactly one OCR run per RDP (enforced by the OneToOne relation);
    re-running is not supported. See docs/src/flows/rdp_ocr.md.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        IN_PROGRESS = "IN_PROGRESS", _("In progress")
        COMPLETED = "COMPLETED", _("Completed")
        FAILED = "FAILED", _("Failed")

    rdp = models.OneToOneField("Rdp", on_delete=models.CASCADE, related_name="ocr_run")
    correlation_id = models.UUIDField(unique=True, default=uuid4, editable=False)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)
    batch_total = models.PositiveIntegerField(default=0)
    received_batch_ids = models.JSONField(default=list, blank=True)
    results = models.JSONField(default=dict, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("OCR run")
        verbose_name_plural = _("OCR runs")

    def __str__(self) -> str:
        return f"OcrRun({self.correlation_id}) rdp={self.rdp_id} status={self.status}"
