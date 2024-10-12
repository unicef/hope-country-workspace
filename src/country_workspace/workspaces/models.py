from django.db import models

from hope_flex_fields.models import DataChecker

from country_workspace.models import Household, Individual, Office, Program

__all__ = ["CountryProgram", "CountryHousehold", "CountryIndividual"]


class CountryHousehold(Household):
    class Meta:
        proxy = True
        verbose_name = "Country Household"
        verbose_name_plural = "Country Households"
        # app_label = "country_workspace"


class CountryIndividual(Individual):
    class Meta:
        proxy = True
        # app_label = "country_workspace"


class CountryProgram(Program):
    class Meta:
        proxy = True
        # app_label = "country_workspace"


class CountryChecker(DataChecker):
    country_office = models.ForeignKey(Office, on_delete=models.CASCADE)

    # class Meta:
    #     app_label = "workspaces"
