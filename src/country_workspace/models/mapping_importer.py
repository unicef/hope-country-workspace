from typing import Any
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from hope_flex_fields.models import DataChecker

from country_workspace.models.base import BaseModel
from country_workspace.validators.mapping import FieldMappingRulesValidator


class MappingImporter(BaseModel):
    data_checker = models.OneToOneField(DataChecker, on_delete=models.CASCADE, related_name="%(class)s")
    name = models.CharField(max_length=255)
    description = models.CharField(max_length=255, blank=True)
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

    def __str__(self) -> str:
        return self.name

    def apply(self, data: dict[str, Any]) -> dict[str, Any]:
        """Apply mapping rules to transform field names."""
        if not self.rules:
            return data

        for rule in (line.strip() for line in self.rules.splitlines()):
            old_field, new_field = rule.split("=", 1)
            if old_field in data:
                data[new_field] = data.pop(old_field)

        return data
