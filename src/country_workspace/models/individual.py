from django.db import models
from django.utils.functional import cached_property

from hope_flex_fields.models import DataChecker

from .base import BaseModel, Validable
from .household import Household


class Individual(Validable, BaseModel):
    household = models.ForeignKey(Household, on_delete=models.CASCADE, null=True, blank=True)
    system_fields = models.JSONField(default=dict, blank=True)

    def __str__(self) -> str:
        return self.name

    @cached_property
    def checker(self) -> "DataChecker":
        return self.program.individual_checker
