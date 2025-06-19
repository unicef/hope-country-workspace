from typing import Any
from mptt.models import MPTTModel
from mptt.fields import TreeForeignKey
from functools import reduce

from jmespath import search, Options, exceptions
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError

from country_workspace.models.base import TimestampMixin
from country_workspace.validators.mapping import JMESPathValidator


class MappingProfile(TimestampMixin, MPTTModel):
    """Hierarchical mapping profile."""

    class SourceType(models.TextChoices):
        ANY = "ANY", _("Any Source")
        AURORA = "AURORA", _("Aurora REST API")
        KOBO = "KOBO", _("Kobo REST API")
        XLS = "XLSX", _("Excel Files")

    class ImportSchema(models.TextChoices):
        ANY = "ANY", _("Any Structure")
        HH_IND = "HH_IND", _("Household + Individuals")
        PEOPLE = "PEOPLE", _("People only")

    name = models.CharField(max_length=255)
    description = models.CharField(max_length=255, blank=True)
    program = models.ManyToManyField(
        "Program", blank=True, related_name="%(class)ss", help_text=_("Programs this profile is associated with")
    )
    parent = TreeForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="%(class)ss",
        help_text=_("Parent profile for inheritance"),
    )
    source_type = models.CharField(max_length=50, choices=SourceType.choices, default=SourceType.ANY, db_index=True)
    import_schema = models.CharField(
        max_length=50, choices=ImportSchema.choices, default=ImportSchema.ANY, db_index=True
    )
    is_active = models.BooleanField(default=True, db_index=True)

    class MPTTMeta:
        order_insertion_by = ["name"]

    class Meta:
        verbose_name = "Mapping Profile"
        verbose_name_plural = "Mapping Profiles"
        indexes = [
            models.Index(fields=["source_type", "import_schema", "is_active"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(parent=models.F("pk")),
                name="mapping_profile_not_self_parent",
                violation_error_message=_("Profile cannot be its own parent"),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.source_type}/{self.import_schema})"

    def clean(self) -> None:
        if self.parent:
            if self.parent.source_type not in [self.SourceType.ANY, self.source_type]:
                raise ValidationError("Incompatible source_type with parent")
            if self.parent.import_schema not in [self.ImportSchema.ANY, self.import_schema]:
                raise ValidationError("Incompatible import_schema with parent")

    def get_inheritance_chain(self) -> str:
        ancestors = self.get_ancestors(include_self=True)
        return "-" if len(ancestors) == 1 else " → ".join(ancestor.name for ancestor in ancestors)

    def get_all_rules(self) -> list["FieldMappingRule"]:
        """Get active rules from profile hierarchy, sorted by order, with child overriding parent rules."""
        ancestors = self.get_ancestors(include_self=True).prefetch_related("rules")
        unique_rules = {rule.name: rule for ancestor in ancestors for rule in ancestor.rules.all() if rule.is_active}
        return sorted(unique_rules.values(), key=lambda r: r.order)

    def apply_all_rules(self, data: dict[str, Any]) -> dict[str, Any]:
        """Apply all active rules from this profile and its ancestors to the data."""
        if not data:
            return data
        return reduce(lambda result, rule: rule.apply(result), self.get_all_rules(), data)


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
