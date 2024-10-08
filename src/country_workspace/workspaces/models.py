from django.db import models

from hope_flex_fields.models import DataChecker

from country_workspace import models as global_models
from country_workspace.models import Office

__all__ = ["CountryProgram", "CountryHousehold", "CountryIndividual"]


class CountryHousehold(global_models.Household):
    class Meta:
        proxy = True
        # verbose_name = "Household"
        # verbose_name_plural = "Households"
        # app_label = "country_workspace"


class CountryIndividual(global_models.Individual):
    class Meta:
        proxy = True
        # app_label = "country_workspace"


class CountryProgram(global_models.Program):
    class Meta:
        proxy = True
        # app_label = "country_workspace"


class CountryChecker(DataChecker):
    country_office = models.ForeignKey(Office, on_delete=models.CASCADE)

    # class Meta:
    #     app_label = "workspaces"
