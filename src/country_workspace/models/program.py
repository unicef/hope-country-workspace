from contextlib import suppress
from typing import TYPE_CHECKING, Iterable

from django.core.exceptions import ObjectDoesNotExist
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
    extra_fields = models.JSONField(default=dict, blank=True, null=False)
    enabled = models.BooleanField(default=True, db_index=True, help_text="Is this program enabled in the workspace?")

    serializer = models.ForeignKey(DataSerializer, on_delete=models.SET_NULL, null=True, blank=True)

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

    def get_checker_for(self, m: type[Validable] | Validable) -> DataChecker:
        from country_workspace.models import Household, Individual
        from country_workspace.workspaces.models import CountryHousehold, CountryIndividual

        if isinstance(m, (Household | CountryHousehold)) or m in (Household, CountryHousehold):
            return self.household_checker
        if isinstance(m, (Individual | CountryIndividual)) or m in (Individual, CountryIndividual):
            return self.individual_checker
        raise ValueError(m)

    def get_columns_for(self, model_cls: type[Validable]) -> list[str]:
        from country_workspace.models import Household, Individual

        if issubclass(model_cls, Household):
            raw = self.household_columns
        elif issubclass(model_cls, Individual):
            raw = self.individual_columns
        else:
            raise TypeError(f"Unsupported model {model_cls!r}")

        return [c.strip() for c in raw.splitlines() if c.strip()]

    def serialize(self, data: list[dict]) -> Iterable:
        if self.serializer:
            return self.serializer.serialize(data)
        return data

    def apply_mapping_importer(
        self, m: type[Validable] | Validable, data: dict[str, str | int | bool]
    ) -> dict[str, str | int | bool]:
        # skip if mapping importer not found
        with suppress(ObjectDoesNotExist):
            self.get_checker_for(m).mappingimporter.apply(data)
        return data
