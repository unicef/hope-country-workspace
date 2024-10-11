from django.db import models

from .base import BaseModel
from .household import Household
from .office import Office
from .program import Program


class Individual(BaseModel):
    country_office = models.ForeignKey(Office, on_delete=models.CASCADE)
    program = models.ForeignKey(Program, on_delete=models.CASCADE)

    household = models.ForeignKey(Household, on_delete=models.CASCADE, null=True, blank=True)

    name = models.CharField(max_length=255, null=True, blank=True)
    flex_fields = models.JSONField(default=dict, blank=True)

    system_fields = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return self.name
