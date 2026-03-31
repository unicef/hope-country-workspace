from typing import TYPE_CHECKING, Any
from collections.abc import Iterable
from enum import StrEnum

from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.utils.translation import gettext as _
from hope_flex_fields.models import DataChecker
from strategy_field.fields import StrategyField
from strategy_field.utils import fqn

from country_workspace.models.beneficiary_group import BeneficiaryGroup
from country_workspace.models.office import Office
from .data_serializer import DataSerializer

from ..validators.registry import NoopValidator, beneficiary_validator_registry
from .base import BaseModel, Validable

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from .household import Household
    from .individual import Individual


class BeneficiaryScope(StrEnum):
    HOUSEHOLD = "household"
    INDIVIDUAL = "individual"


class Program(BaseModel):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    FINISHED = "FINISHED"
    STATUS_CHOICE = (
        (ACTIVE, _("Active")),
        (DRAFT, _("Draft")),
        (FINISHED, _("Finished")),
    )
    CHILD_PROTECTION = "CHILD_PROTECTION"
    EDUCATION = "EDUCATION"
    HEALTH = "HEALTH"
    MULTI_PURPOSE = "MULTI_PURPOSE"
    NUTRITION = "NUTRITION"
    SOCIAL_POLICY = "SOCIAL_POLICY"
    WASH = "WASH"
    SECTOR_CHOICE = (
        (CHILD_PROTECTION, _("Child Protection")),
        (EDUCATION, _("Education")),
        (HEALTH, _("Health")),
        (MULTI_PURPOSE, _("Multi Purpose")),
        (NUTRITION, _("Nutrition")),
        (SOCIAL_POLICY, _("Social Policy")),
        (WASH, _("WASH")),
    )
    hope_id = models.CharField(max_length=200, unique=True, editable=False)
    beneficiary_group = models.ForeignKey(
        BeneficiaryGroup,
        on_delete=models.PROTECT,
        related_name="programs",
        null=True,
        blank=True,
        help_text="Beneficiary group to which this program belongs",
    )
    country_office = models.ForeignKey(Office, on_delete=models.CASCADE, related_name="programs")
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICE, db_index=True)
    sector = models.CharField(max_length=50, choices=SECTOR_CHOICE, db_index=True)
    # Local Fields
    beneficiary_validator = StrategyField(
        registry=beneficiary_validator_registry,
        default=fqn(NoopValidator),
        blank=True,
        null=True,
        help_text="Validator to use to validate the whole Household",
    )
    household_checker = models.ForeignKey(
        DataChecker,
        blank=True,
        null=True,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Checker to use with Household's records",
    )

    individual_checker = models.ForeignKey(
        DataChecker,
        blank=True,
        null=True,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Checker to use with Individual's records",
    )

    household_search = models.TextField(default="name", help_text="Fields to use for searches")
    individual_search = models.TextField(default="name", help_text="Fields to use for searches")
    household_columns = models.TextField(default="name\nid", help_text="Columns to display in the Admin table")
    individual_columns = models.TextField(default="name\nid", help_text="Columns to display in the Admin table")
    hh_alien_columns_to_ignore = models.TextField(
        blank=True, null=True, default=None, help_text="Alien fields to ignore"
    )
    ind_alien_columns_to_ignore = models.TextField(
        blank=True, null=True, default=None, help_text="Alien fields to ignore"
    )
    alien_validation_enabled = models.BooleanField(
        default=True,
        help_text="Should alien-field validation run for this programme?",
    )
    extra_fields = models.JSONField(default=dict, blank=True, null=False)
    enabled = models.BooleanField(default=True, db_index=True, help_text="Is this program enabled in the workspace?")
    serializer = models.ForeignKey(DataSerializer, on_delete=models.SET_NULL, null=True, blank=True)
    # Internal metadata used by the workspace.
    # Expected JSON structure (simplified):
    # - key "default_fields": an object with two optional keys:
    #   - "household":  mapping "<field_name>" -> <default_value>
    #   - "individual": mapping "<field_name>" -> <default_value>
    # - other keys may be added in the future.
    system_fields = models.JSONField(
        default=dict,
        blank=True,
        help_text=_('Internal metadata (e.g. "default_fields" for household/individual defaults).'),
    )
    biometric_deduplication_enabled = models.BooleanField(
        default=False,
        help_text="Is biometric deduplication enabled for this program?",
    )

    def __str__(self) -> str:
        return self.name

    class Meta:
        verbose_name = _("Programme")
        verbose_name_plural = _("Programmes")
        permissions = (("import_program_data", "Can Import beneficiaries"),)

    @property
    def households(self) -> "QuerySet[Household]":
        from country_workspace.models import Household

        return Household.objects.filter(batch__program=self)

    @property
    def individuals(self) -> "QuerySet[Individual]":
        from country_workspace.models import Individual

        return Individual.objects.filter(batch__program=self)

    @property
    def is_master_detail(self) -> bool:
        return self.beneficiary_group is None or self.beneficiary_group.master_detail

    @property
    def unicef_id(self) -> str:
        if not self.code or not getattr(self.country_office, "slug", None):
            raise ImproperlyConfigured("Program.unicef_id requires country_office.slug and Program.code")
        return f"{self.country_office.slug}-{self.code.lower()}"

    @staticmethod
    def _scope_for(m: type[Validable] | Validable) -> BeneficiaryScope:
        """Return 'household' or 'individual' for a given model class or instance."""
        from country_workspace.models import Household, Individual

        cls = m if isinstance(m, type) else type(m)
        if issubclass(cls, Household):
            return BeneficiaryScope.HOUSEHOLD
        if issubclass(cls, Individual):
            return BeneficiaryScope.INDIVIDUAL
        raise TypeError(f"Unsupported model {m!r}")

    def get_checker_for(self, m: type[Validable] | Validable) -> DataChecker | None:
        scope = self._scope_for(m)
        return getattr(self, f"{scope.value}_checker")

    def get_columns_for(self, m: type[Validable]) -> list[str]:
        """Return list of column names for the given model class."""
        scope = self._scope_for(m)
        raw = getattr(self, f"{scope.value}_columns")
        return [c.strip() for c in raw.splitlines() if c.strip()]

    def serialize(self, data: list[dict]) -> Iterable:
        if self.serializer:
            return self.serializer.serialize(data)
        return data

    def apply_mapping_importer(
        self,
        m: type[Validable] | Validable,
        data: dict[str, Any],
        mapping_id: int | None = None,
    ) -> dict[str, Any]:
        """Apply mapping importer(s)."""
        from country_workspace.models import MappingImporter

        if mapping_id is not None:
            if importer := MappingImporter.objects.filter(id=mapping_id).first():
                data = importer.apply(data)
        elif checker := self.get_checker_for(m):
            for importer in checker.mapping_importers.filter(office=self.country_office):
                data = importer.apply(data)
        return data

    def get_default_fields_for(self, m: type[Validable] | Validable) -> dict[str, Any]:
        """Return defaults from system_fields['default_fields'][scope] for the given model."""
        scope = self._scope_for(m).value
        default_fields = (self.system_fields or {}).get("default_fields") or {}
        raw = default_fields.get(scope) or {}
        return dict(raw) if isinstance(raw, dict) else {}

    def save_default_fields_for(self, m: type[Validable] | Validable, defaults: dict[str, Any]) -> None:
        """Replace system_fields['default_fields'][scope] with the given defaults and save."""
        scope = self._scope_for(m).value

        system_fields = dict(self.system_fields or {})
        default_fields = dict(system_fields.get("default_fields") or {})

        default_fields[scope] = defaults
        system_fields["default_fields"] = default_fields

        self.system_fields = system_fields
        self.save(update_fields=["system_fields"])

    def apply_default_fields(self, m: type[Validable] | Validable, data: dict[str, Any]) -> dict[str, Any]:
        """Apply default fields for the given model to the provided data dict."""
        if not (defaults := self.get_default_fields_for(m)):
            return data
        for field_name, default_value in defaults.items():
            if field_name not in data or data[field_name] is None:
                data[field_name] = default_value
        return data

    def has_any_data(self) -> bool:
        return self.households.exists() or self.individuals.exists()

    def get_unique_field_for(self, m: type[Validable] | Validable) -> str | None:
        scope = self._scope_for(m).value
        unique_fields = (self.system_fields or {}).get("unique_fields") or {}
        value = unique_fields.get(scope)
        return value if isinstance(value, str) and value.strip() else None

    def save_unique_field_for(self, m: type[Validable] | Validable, field_name: str | None) -> None:
        scope = self._scope_for(m).value
        normalized = (field_name or "").strip() or None

        system_fields = dict(self.system_fields or {})
        unique_fields = dict(system_fields.get("unique_fields") or {})
        removed_unique_values = dict(system_fields.get("removed_unique_values") or {})
        scope_removed_values = dict(removed_unique_values.get(scope) or {})

        if normalized is None:
            unique_fields.pop(scope, None)
        else:
            unique_fields[scope] = normalized
            scope_removed_values.setdefault(normalized, [])
            removed_unique_values[scope] = scope_removed_values

        system_fields["unique_fields"] = unique_fields
        system_fields["removed_unique_values"] = removed_unique_values
        self.system_fields = system_fields
        self.save(update_fields=["system_fields"])

    def get_removed_unique_values_for(self, m: type[Validable] | Validable) -> list[str]:
        """Return archived unique values for configured scope+field."""
        if not (field_name := self.get_unique_field_for(m)):
            return []

        scope = self._scope_for(m).value
        removed_unique_values = (self.system_fields or {}).get("removed_unique_values") or {}
        scope_values = removed_unique_values.get(scope) or {}
        values = scope_values.get(field_name) or []
        if not isinstance(values, list):
            return []
        return [str(value) for value in values if value is not None and str(value).strip()]

    def add_removed_unique_values_for(self, m: type[Validable] | Validable, values: Iterable[Any]) -> None:
        """Merge removed values for configured unique field in the given scope."""
        if not (field_name := self.get_unique_field_for(m)):
            return
        scope = self._scope_for(m).value

        normalized_values = {str(value).strip() for value in values if value is not None and str(value).strip()}
        if not normalized_values:
            return

        system_fields = dict(self.system_fields or {})
        removed_unique_values = dict(system_fields.get("removed_unique_values") or {})
        scope_values = dict(removed_unique_values.get(scope) or {})
        existing_values = scope_values.get(field_name) or []
        existing_set = {str(value).strip() for value in existing_values if value is not None and str(value).strip()}

        scope_values[field_name] = sorted(existing_set | normalized_values)
        removed_unique_values[scope] = scope_values
        system_fields["removed_unique_values"] = removed_unique_values

        self.system_fields = system_fields
        self.save(update_fields=["system_fields"])
