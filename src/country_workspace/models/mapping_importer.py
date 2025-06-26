from typing import Any
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from country_workspace.models.base import BaseModel
from country_workspace.validators.mapping import FieldMappingRulesValidator


class MappingImporter(BaseModel):
    country_office = models.ForeignKey("Office", on_delete=models.CASCADE, related_name="%(class)ss")
    program = models.ForeignKey("Program", on_delete=models.CASCADE, related_name="%(class)ss")
    name = models.CharField(max_length=255, blank=True, default="")
    description = models.CharField(max_length=255, blank=True)
    rules = models.TextField(
        blank=True,
        default="",
        validators=[FieldMappingRulesValidator()],
        help_text=_(
            "Field mapping rules (one per line). Format: `sheet_name:field_name=datachecker name:field_name`. "
            "Example: Individuals:gender=HOPE Individual core:sex"
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="%(class)ss"
    )

    class Meta:
        verbose_name = _("Mapping Importer")
        verbose_name_plural = _("Mapping Importers")
        constraints = [
            models.UniqueConstraint(
                fields=["name"],
                condition=~models.Q(name=""),
                name="unique_non_empty_name",
                violation_error_message=_("A mapping importer with this name already exists."),
            )
        ]

    def __str__(self) -> str:
        return self.name or f"Mapping Importer # {self.pk}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.program_id and self.country_office_id is None:
            self.country_office_id = self.program.country_office_id
        super().save(*args, **kwargs)

    def apply(self, sheet_name: str, data: dict[str, Any]) -> dict[str, Any]:
        """Apply mapping rules to transform data from sheet format to datachecker format."""
        if not self.rules:
            return data

        FieldMappingRulesValidator()(self.rules)

        for rule in (line.strip() for line in self.rules.splitlines()):
            left, right = rule.split("=", 1)
            rule_sheet, sheet_field = left.split(":", 1)
            datachecker_field = right.rsplit(":", 1)[1]

            if rule_sheet == sheet_name and sheet_field in data:
                data[datachecker_field] = data.pop(sheet_field)

        return data
