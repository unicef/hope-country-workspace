from django.db import models
from django.utils.translation import gettext as _

from .base import BaseModel
from .user import User


class Batch(BaseModel):
    class BatchSource(models.TextChoices):
        RDI = "RDI", "Rdi file"
        AURORA = "AURORA", "Aurora"
        KOBO = "KOBO", "Kobo"

    country_office = models.ForeignKey("Office", on_delete=models.CASCADE, related_name="%(class)ss")
    program = models.ForeignKey("Program", on_delete=models.CASCADE, related_name="%(class)ss")
    name = models.CharField(max_length=255, blank=True, null=True)
    import_date = models.DateTimeField(auto_now=True, db_index=True)
    imported_by = models.ForeignKey(User, on_delete=models.CASCADE)
    source = models.CharField(max_length=255, blank=True, null=True, choices=BatchSource.choices)

    class Meta:
        unique_together = (("import_date", "name"),)
        verbose_name = _("Batch")
        verbose_name_plural = _("Batches")

    def __str__(self) -> str:
        return self.name or f"Batch self.pk ({self.country_office})"
