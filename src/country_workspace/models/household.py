from functools import cached_property
from typing import TYPE_CHECKING

from django.db import models

from .base import BaseModel, Validable

if TYPE_CHECKING:
    from hope_flex_fields.models import DataChecker

    from .office import Office
    from .program import Program


class Household(Validable, BaseModel):
    system_fields = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Household"

    def __str__(self) -> str:
        return self.name or "Household %s" % self.id

    @cached_property
    def checker(self) -> "DataChecker":
        return self.program.household_checker

    @cached_property
    def program(self) -> "Program":
        return self.batch.program

    @cached_property
    def country_office(self) -> "Office":
        return self.batch.program.country_office
