from functools import cached_property
from typing import TYPE_CHECKING

from django.db import models

from .base import BaseModel, Validable

if TYPE_CHECKING:
    from hope_flex_fields.models import DataChecker


class Household(Validable, BaseModel):
    system_fields = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Household"

    def __str__(self) -> str:
        return self.name

    @cached_property
    def checker(self) -> "DataChecker":
        return self.program.household_checker
