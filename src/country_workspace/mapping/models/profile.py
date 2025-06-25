from typing import Any
from mptt.models import MPTTModel
from mptt.fields import TreeForeignKey
from functools import reduce

from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError

from country_workspace.models.base import TimestampMixin
from country_workspace.mapping.models.field_mapping_rule import FieldMappingRule


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
        "country_workspace.Program",
        blank=True,
        related_name="%(class)ss",
        help_text=_("Programs this profile is associated with"),
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

    def get_all_rules(self) -> list[FieldMappingRule]:
        """Get active rules from profile hierarchy, sorted by order, with child overriding parent rules."""
        ancestors = self.get_ancestors(include_self=True).prefetch_related("rules")
        unique_rules = {rule.name: rule for ancestor in ancestors for rule in ancestor.rules.all() if rule.is_active}
        return sorted(unique_rules.values(), key=lambda r: r.order)

    def apply_all_rules(self, data: dict[str, Any]) -> dict[str, Any]:
        """Apply all active rules from this profile and its ancestors to the data."""
        if not data:
            return data
        return reduce(lambda result, rule: rule.apply(result), self.get_all_rules(), data)
