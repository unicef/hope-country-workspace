from django.db import models
from django.utils.functional import cached_property

from hope_flex_fields.models import DataChecker

from .base import BaseModel, Validable
from .household import Household


class Individual(Validable, BaseModel):
    household = models.ForeignKey(Household, on_delete=models.CASCADE, null=True, blank=True, related_name="members")
    system_fields = models.JSONField(default=dict, blank=True)

    @cached_property
    def checker(self) -> "DataChecker":
        return self.program.individual_checker

    @cached_property
    def program(self) -> "DataChecker":
        return self.household.batch.program

    @cached_property
    def country_office(self) -> "DataChecker":
        return self.household.batch.program.country_office
