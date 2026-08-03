import pghistory
from typing import TYPE_CHECKING, Final
from functools import cached_property
from django.db import models
from django.utils.translation import gettext as _

from .base import BaseModel, Validable
from .household import Household
from .mixins import FlexFieldGroupingMixin, HopeBlobMixin

if TYPE_CHECKING:
    from hope_flex_fields.models import DataChecker
    from .office import Office
    from .program import Program


INDEX_NAME_PREFIX: Final[str] = "%(app_label)s_%(class)s"


@pghistory.track(pghistory.UpdateEvent(condition=pghistory.AnyChange("flex_fields", "flex_files", "removed")))
class Individual(HopeBlobMixin, FlexFieldGroupingMixin, Validable, BaseModel):
    HOPE_BLOB_ENTITY = "ind"

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
        # Identity collision errors are set at import time only — preserve them
        # across re-validations since validate_with_checker replaces errors wholesale.
        identity_error = self.errors.get("identity")
        super().validate_with_checker(fail_if_alien=fail_if_alien)
        if identity_error and "identity" not in self.errors:
            self.errors["identity"] = identity_error
            self.save(update_fields=["errors"])
        return not bool(self.errors)
