from functools import cached_property
from typing import TYPE_CHECKING, Final, override

import pghistory
from django.db import models
from django.utils import timezone

from .base import BaseModel, Validable
from .mixins import FlexFieldGroupingMixin

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from hope_flex_fields.models import DataChecker

    from .individual import Individual
    from .office import Office
    from .program import Program


RELATIONSHIP_HEAD: Final[str] = "HEAD"
RELATIONSHIP_FIELDNAME: Final[str] = "relationship"

ROLE_PRIMARY: Final[str] = "PRIMARY"
ROLE_ALTERNATE: Final[str] = "ALTERNATE"


@pghistory.track(pghistory.UpdateEvent(condition=pghistory.AnyChange("flex_fields", "flex_files", "removed")))
class Household(FlexFieldGroupingMixin, Validable, BaseModel):
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

    @override
    def validate_with_checker(self, fail_if_alien: bool = False) -> bool:
        super().validate_with_checker(fail_if_alien=fail_if_alien)

        members_failed = False
        for ind in self.members.all():
            members_failed |= not ind.validate_with_checker(fail_if_alien=fail_if_alien)

        ext_msgs = self.program.beneficiary_validator.validate(self)

        changed = False
        if members_failed or ext_msgs:
            dct = self.errors.setdefault("dct", [])
            if members_failed:
                dct.append("Some members did not validate")
            if ext_msgs:
                dct.extend(ext_msgs)
            changed = True

        from country_workspace.utils.collision import check_identity_collision

        errors_before = dict(self.errors)
        check_identity_collision(self)
        if self.errors != errors_before:
            changed = True

        if changed:
            self.last_checked = timezone.now()
            self.save(update_fields=["errors", "last_checked"])

        return not bool(self.errors)

    @property
    def head(self) -> "QuerySet[Individual]":
        return self.flex_fields.get("head_of_household_id", self.flex_fields.get("head_of_household"))

    @property
    def primary_collector(self) -> "QuerySet[Individual]":
        return self.flex_fields.get("primary_collector_id", self.flex_fields.get("primary_collector"))

    @property
    def alternate_collector(self) -> "QuerySet[Individual]":
        return self.flex_fields.get("alternate_collector_id", self.flex_fields.get("alternate_collector"))
