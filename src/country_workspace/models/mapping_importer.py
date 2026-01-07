from typing import Any
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from hope_flex_fields.models import DataChecker

from country_workspace.models.base import BaseModel
from country_workspace.validators.mapping import FieldMappingRulesValidator


class MappingImporter(BaseModel):
    name = models.CharField(max_length=255)
    description = models.CharField(max_length=255, blank=True)
    office = models.ForeignKey(
        "Office",
        on_delete=models.CASCADE,
        related_name="mapping_importers",
        help_text=_("Business Area (Office) this mapping belongs to"),
    )
    data_checker = models.ForeignKey(
        DataChecker,
        on_delete=models.CASCADE,
        related_name="mapping_importers",
        help_text=_("DataChecker (Household/Individual) this mapping is valid for"),
    )
    rules = models.TextField(
        blank=True,
        default="",
        validators=[FieldMappingRulesValidator()],
        help_text=_("Field mapping rules (one per line). Format: %(format)s. Example: %(example)s")
        % {"format": "`external_fieldname=internal_fieldname`", "example": "`gender=sex`"},
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="%(class)ss"
    )

    class Meta:
        verbose_name = _("Mapping Importer")
        verbose_name_plural = _("Mapping Importers")
        unique_together = [["office", "name"]]

    def __str__(self) -> str:
        return self.name

    @property
    def rules_as_dict(self) -> dict[str, str]:
        if not self.rules:
            return {}
        return {
            old_field.strip(): new_field.strip()
            for raw in self.rules.splitlines()
            if (line := raw.strip())
            for old_field, new_field in (line.split("=", 1),)
        }

    def apply(self, data: dict[str, Any]) -> dict[str, Any]:
        """Apply mapping rules to transform field names."""
        if not self.rules:
            return data

        for external, internal in self.rules_as_dict.items():
            if external in data:
                data[internal] = data.pop(external)

        return data
