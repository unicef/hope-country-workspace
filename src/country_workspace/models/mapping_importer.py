from typing import Any
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from hope_flex_fields.models import DataChecker

from country_workspace.models.base import BaseModel
from country_workspace.validators.mapping import FieldMappingRulesValidator, ValueTransformationRulesValidator


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
    value_transformations = models.TextField(
        blank=True,
        default="",
        validators=[ValueTransformationRulesValidator()],
        help_text=_(
            "Value transformation rules (one per line). Format: %(format)s. "
            "Example: %(example)s. These transformations are applied after field name mapping."
        )
        % {"format": "`fieldname:old_value=new_value`", "example": "`sex:M=MALE` or `sex:F=FEMALE`"},
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

        return dict(line.split("=", 1) for line in self.rules.splitlines())

    @property
    def value_transformations_as_dict(self) -> dict[str, dict[str, str]]:
        """Parse value transformation rules into a nested dict: {fieldname: {old_value: new_value}}."""
        if not self.value_transformations:
            return {}

        transformations: dict[str, dict[str, str]] = {}
        for line in self.value_transformations.splitlines():
            line = line.strip()  # noqa: PLW2901
            if not line:
                continue

            # Format: fieldname:old_value=new_value
            if ":" not in line or "=" not in line:
                continue

            field_part, value_part = line.split(":", 1)
            field_name = field_part.strip()
            if "=" not in value_part:
                continue

            old_value, new_value = (val.strip() for val in value_part.split("=", 1))
            if field_name not in transformations:
                transformations[field_name] = {}
            transformations[field_name][old_value] = new_value

        return transformations

    def _apply_field_mapping(self, data: dict[str, Any]) -> dict[str, Any]:
        if not self.rules:
            return data

        for external, internal in self.rules_as_dict.items():
            if external in data:
                data[internal] = data.pop(external)
        return data

    def _apply_value_transformations(self, data: dict[str, Any]) -> dict[str, Any]:
        if not self.value_transformations:
            return data

        transformations = self.value_transformations_as_dict
        for field_name, value_map in transformations.items():
            if field_name in data:
                current_value = str(data[field_name])
                if current_value in value_map:
                    data[field_name] = value_map[current_value]
        return data

    def apply(self, data: dict[str, Any]) -> dict[str, Any]:
        data = self._apply_field_mapping(data)
        return self._apply_value_transformations(data)
