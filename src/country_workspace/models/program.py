from typing import Union

from django.db import models
from django.utils.translation import gettext as _

from hope_flex_fields.models import DataChecker
from strategy_field.fields import StrategyField
from strategy_field.utils import fqn

from ..validators.registry import NoopValidator, beneficiary_validator_registry
from .base import BaseModel, Validable
from .office import Office


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
    country_office = models.ForeignKey(Office, on_delete=models.CASCADE, related_name="programs")
    name = models.CharField(max_length=255)
    programme_code = models.CharField(max_length=255)
    status = models.CharField(max_length=10, choices=STATUS_CHOICE, db_index=True)
    sector = models.CharField(max_length=50, choices=SECTOR_CHOICE, db_index=True)
    active = models.BooleanField(default=False)

    # Local Fields
    beneficiary_validator = StrategyField(
        registry=beneficiary_validator_registry, default=fqn(NoopValidator), blank=True, null=True
    )
    household_checker = models.ForeignKey(
        DataChecker, blank=True, null=True, on_delete=models.CASCADE, related_name="+"
    )

    individual_checker = models.ForeignKey(
        DataChecker, blank=True, null=True, on_delete=models.CASCADE, related_name="+"
    )

    household_search = models.TextField(default="name", help_text="Fields to use for searches")
    individual_search = models.TextField(default="name", help_text="Fields to use for searches")
    household_columns = models.TextField(default="name\nid", help_text="Columns to display ib the Admin table")
    individual_columns = models.TextField(default="name\nid", help_text="Columns to display ib the Admin table")

    def __str__(self) -> str:
        return self.name

    class Meta:
        verbose_name = _("Programme")
        verbose_name_plural = _("Programmes")

    @property
    def households(self):
        from country_workspace.models import Household

        return Household.objects.filter(batch__program=self)

    @property
    def individuals(self):
        from country_workspace.models import Individual

        return Individual.objects.filter(batch__program=self)

    def get_checker_for(self, m: Union[type[Validable], Validable]) -> DataChecker:
        from country_workspace.models import Household, Individual

        if isinstance(m, Household) or m == Household:
            return self.household_checker
        elif isinstance(m, Individual) or m == Individual:
            return self.individual_checker
        else:
            raise ValueError(m)
