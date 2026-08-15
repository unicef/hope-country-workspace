from typing import Any

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext as _

from .base import BaseModel
from .user import User


class Batch(BaseModel):
    class BatchStatus(models.TextChoices):
        LOADING = "LOADING", "Loading"
        COMPLETE = "COMPLETE", "Complete"

    class BatchSource(models.TextChoices):
        RDI = "RDI", "Rdi file"
        AURORA = "AURORA", "Aurora"
        KOBO = "KOBO", "Kobo"

    country_office = models.ForeignKey("Office", on_delete=models.CASCADE, related_name="%(class)ss")
    program = models.ForeignKey("Program", on_delete=models.CASCADE, related_name="%(class)ss")
    name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text=_("Name of this import batch."),
    )
    import_date = models.DateTimeField(
        auto_now=True,
        help_text=_("Date and time this batch was created."),
    )
    imported_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        help_text=_("User who started the import."),
    )
    source = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        choices=BatchSource.choices,
        help_text=_("Where the records were imported from (RDI file, Aurora, or Kobo)."),
    )
    status = models.CharField(
        max_length=32,
        choices=BatchStatus.choices,
        default=BatchStatus.LOADING,
        db_index=True,
        help_text=_(
            "Loading while the import is still processing. Complete when the source-specific import has finished. "
            "Validation may continue afterwards."
        ),
    )
    picture_import_state = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = (("import_date", "name"),)
        verbose_name = _("Batch")
        verbose_name_plural = _("Batches")
        permissions = (("reprocess_batch", "Can reprocess batch"),)

    def __str__(self) -> str:
        return self.name or f"Batch self.pk ({self.country_office})"

    def get_picture_import_state(self) -> dict[str, Any]:
        state = self.picture_import_state
        if not isinstance(state, dict):
            return {}
        return state

    def start_picture_import(self, *, payload: dict[str, Any], user: User) -> dict[str, Any] | None:
        previous = self.get_picture_import_state() or None
        self.picture_import_state = {
            **payload,
            "updated_by": user.pk,
            "updated_at": timezone.now().isoformat(),
        }
        self.save(update_fields=["picture_import_state"])
        return previous

    def finish_picture_import(self) -> dict[str, Any] | None:
        payload = self.get_picture_import_state() or None
        self.picture_import_state = {}
        self.save(update_fields=["picture_import_state"])
        return payload
