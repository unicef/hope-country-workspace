from functools import cached_property
from typing import TYPE_CHECKING

import pghistory
from django.db import models
from django.utils import timezone

from .base import BaseModel, Validable

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from hope_flex_fields.models import DataChecker

    from .individual import Individual
    from .office import Office
    from .program import Program


@pghistory.track(
    pghistory.UpdateEvent("updates", condition=pghistory.AnyChange("flex_fields", "flex_files", "removed"))
)
class Household(Validable, BaseModel):
    system_fields = models.JSONField(default=dict, blank=True)
    members: "QuerySet[Individual]"

    class Meta:
        verbose_name = "Household"

    @cached_property
    def checker(self) -> "DataChecker":
        return self.program.household_checker

    @cached_property
    def program(self) -> "Program":
        return self.batch.program

    @cached_property
    def country_office(self) -> "Office":
        return self.batch.program.country_office

    def validate_with_checker(self) -> bool:
        hh_valid = True
        for ind in self.members.all():
            if not ind.validate_with_checker():
                hh_valid = False
        if hh_valid:
            super().validate_with_checker()
            errors = self.program.beneficiary_validator.validate(self)
            if errors:
                self.errors["dct"] = errors
        else:
            self.errors["dct"] = ["Some member did not validate"]
        self.last_checked = timezone.now()
        self.save(update_fields=["errors", "last_checked"])
        return not bool(self.errors)

    # Business methods

    def heads(self) -> "QuerySet[Individual]":
        return self.members.filter(flex_fields__relationship="HEAD")

    def collectors_primary(self) -> "QuerySet[Individual]":
        return self.members.filter(flex_fields__primary_collector_id=self.flex_fields["household_id"])

    def collectors_alternate(self) -> "QuerySet[Individual]":
        return self.members.filter(flex_fields__alternate_collector_id=self.flex_fields["household_id"])
