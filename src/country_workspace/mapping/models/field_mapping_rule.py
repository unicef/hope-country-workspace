from typing import Any
from jmespath import search, Options, exceptions
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError

from country_workspace.models.base import TimestampMixin
from country_workspace.mapping.validators import JMESPathValidator


class FieldMappingRule(TimestampMixin, models.Model):
    profile = models.ForeignKey(
        "MappingProfile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rules",
        help_text="Mapping profile this rule belongs to",
    )
    name = models.CharField(max_length=255)
    expression = models.TextField(
        blank=True,
        validators=[JMESPathValidator()],
        help_text="JMESPath expression that returns object with new/modified fields only",
    )
    description = models.CharField(max_length=255, blank=True)
    order = models.PositiveIntegerField(default=100, help_text="Order of execution for the rule (lower is earlier)")
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Field Mapping Rule"
        verbose_name_plural = "Field Mapping Rules"
        ordering = ["order", "name"]
        indexes = [
            models.Index(fields=["profile", "is_active", "order"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "name"],
                name="unique_rule_name_per_profile",
                violation_error_message=_("Rule name must be unique within profile"),
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        super().clean()
        if not (self.expression and self.expression.strip()):
            raise ValidationError({"expression": _("Expression is required")})

    def apply(self, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data, dict):
            return {}
        if not (self.expression and self.expression.strip()):
            return data

        try:
            mapped_fields = search(self.expression.strip(), data, options=Options(custom_functions=None))
            return {**data, **mapped_fields} if isinstance(mapped_fields, dict) else data
        except exceptions.JMESPathError:
            return data
