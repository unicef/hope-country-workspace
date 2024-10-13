from django.db import models

from . import User
from .base import BaseModel


class Batch(BaseModel):
    label = models.CharField(max_length=255, blank=True, null=True)

    import_date = models.DateTimeField(auto_now=True)
    imported_by = models.ForeignKey(User, on_delete=models.CASCADE)

    class Meta:
        unique_together = (("import_date", "label"),)
