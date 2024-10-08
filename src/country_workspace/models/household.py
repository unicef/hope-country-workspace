from django.db import models
from django.utils.translation import gettext as _

from .base import BaseModel
from .office import Office
from .program import Program


class Household(BaseModel):
    country_office = models.ForeignKey(Office, on_delete=models.CASCADE)
    program = models.ForeignKey(Program, on_delete=models.CASCADE)
    name = models.CharField(_("Name"), max_length=255)
    flex_fields = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Household"

    def __str__(self):
        return self.name
