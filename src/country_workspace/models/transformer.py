from typing import Any
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from hope_flex_fields.models import DataChecker

from country_workspace.models.base import BaseModel
from country_workspace.validators.mapping import ValueTransformationRulesValidator


class Transformer(BaseModel):
    name = models.CharField(max_length=255)
    description = models.CharField(max_length=255, blank=True)
    office = models.ForeignKey(
        "Office",
        on_delete=models.CASCADE,
        related_name="transformers",
        help_text=_("Business Area (Office) this transformer belongs to"),
    )
    data_checker = models.ForeignKey(
        DataChecker,
        on_delete=models.CASCADE,
        related_name="transformers",
        help_text=_("DataChecker (Household/Individual) this transformer is valid for"),
    )
    value_transformations = models.TextField(
        blank=True,
        default="",
        validators=[ValueTransformationRulesValidator()],
        help_text=_("Value transformation rules (one per line). Format: %(format)s. Example: %(example)s.")
        % {"format": "`fieldname:old_value=new_value`", "example": "`sex:M=MALE` or `sex:F=FEMALE`"},
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="%(class)ss"
    )

    class Meta:
        verbose_name = _("Transformer")
        verbose_name_plural = _("Transformers")
        unique_together = [["office", "name"]]

    def __str__(self) -> str:
        return self.name

    @property
    def value_transformations_as_dict(self) -> dict[str, dict[str, str]]:
        """Parse value transformation rules into a nested dict: {fieldname: {old_value: new_value}}."""
        if not self.value_transformations:
            return {}

        transformations: dict[str, dict[str, str]] = {}
        for line_num, line in enumerate(self.value_transformations.splitlines(), start=1):
            line = line.strip()  # noqa: PLW2901
            if not line:
                continue

            # Format: fieldname:old_value=new_value
            if ":" not in line or "=" not in line:
                raise ValueError(
                    f"Line {line_num}: Invalid format. Expected format: 'fieldname:old_value=new_value'. "
                    f"Line must contain both ':' and '=' characters. Got: {line!r}"
                )

            field_part, value_part = line.split(":", 1)
            field_name = field_part.strip()
            if "=" not in value_part:
                raise ValueError(
                    f"Line {line_num}: Invalid format. Expected format: 'fieldname:old_value=new_value'. "
                    f"The value part after ':' must contain '='. Got: {line!r}"
                )

            old_value, new_value = (val.strip() for val in value_part.split("=", 1))
            if field_name not in transformations:
                transformations[field_name] = {}
            transformations[field_name][old_value] = new_value

        return transformations

    def apply(self, data: dict[str, Any]) -> dict[str, Any]:
        """Apply value transformations to the data dictionary."""
        if not self.value_transformations:
            return data

        transformations = self.value_transformations_as_dict
        for field_name, value_map in transformations.items():
            if field_name in data:
                current_value = str(data[field_name])
                if current_value in value_map:
                    data[field_name] = value_map[current_value]
        return data
