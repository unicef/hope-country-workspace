import pghistory
from typing import TYPE_CHECKING, Final
from functools import cached_property
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext as _

from .base import BaseModel, Validable
from .household import Household
from .mixins import FlexFieldGroupingMixin

if TYPE_CHECKING:
    from hope_flex_fields.models import DataChecker
    from .office import Office
    from .program import Program


INDEX_NAME_PREFIX: Final[str] = "%(app_label)s_%(class)s"


@pghistory.track(pghistory.UpdateEvent(condition=pghistory.AnyChange("flex_fields", "flex_files", "removed")))
class Individual(FlexFieldGroupingMixin, Validable, BaseModel):
    household = models.ForeignKey(Household, on_delete=models.CASCADE, null=True, blank=True, related_name="members")
    system_fields = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = _("Individual")
        indexes = [
            models.Index(fields=["batch", "removed"], name=f"{INDEX_NAME_PREFIX}_batch_removed_idx"),
            models.Index(fields=["name"], name=f"{INDEX_NAME_PREFIX}_name_idx"),
            models.Index(fields=["batch", "name"], name=f"{INDEX_NAME_PREFIX}_batch_name_idx"),
        ]

    @cached_property
    def checker(self) -> "DataChecker":
        return self.program.individual_checker

    @cached_property
    def program(self) -> "Program":
        return self.batch.program

    @cached_property
    def country_office(self) -> "Office":
        return self.batch.program.country_office

    def validate_with_checker(self, fail_if_alien: bool = False) -> bool:
        super().validate_with_checker(fail_if_alien=fail_if_alien)

        from country_workspace.utils.collision import check_identity_collision

        errors_before = dict(self.errors)
        check_identity_collision(self)
        if self.errors != errors_before:
            self.last_checked = timezone.now()
            self.save(update_fields=["errors", "last_checked"])

        return not bool(self.errors)
