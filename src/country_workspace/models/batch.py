from django.db import models

from .base import BaseModel
from .user import User


class Batch(BaseModel):
    country_office = models.ForeignKey("Office", on_delete=models.CASCADE, related_name="%(class)ss")
    program = models.ForeignKey("Program", on_delete=models.CASCADE, related_name="%(class)ss")
    name = models.CharField(max_length=255, blank=True, null=True)
    import_date = models.DateTimeField(auto_now=True)
    imported_by = models.ForeignKey(User, on_delete=models.CASCADE)

    class Meta:
        unique_together = (("import_date", "name"),)

    def __str__(self):
        return self.name or f"Batch self.pk ({self.country_office})"
