from django.db import models

from .household import Household
from .office import CountryOffice
from .program import Program


class Individual(models.Model):
    country_office = models.ForeignKey(CountryOffice, on_delete=models.CASCADE)
    program = models.ForeignKey(Program, on_delete=models.CASCADE)

    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, null=True, blank=True
    )
    full_name = models.CharField(max_length=255, null=True, blank=True)
    flex_fields = models.JSONField(default=dict, blank=True)
    user_fields = models.JSONField(default=dict, blank=True)
